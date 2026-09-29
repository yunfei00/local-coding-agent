from __future__ import annotations

import asyncio
import os
import tempfile
import unittest
from collections.abc import AsyncIterator
from pathlib import Path
from unittest.mock import patch

from agent.llm.base import ProviderChunk, ProviderError, ToolCall
from agent.permissions.policy import PermissionMode
from agent.server.main import AgentServer


class FakeWebSocket:
    def __init__(self) -> None:
        self.messages: list[dict] = []

    async def send_json(self, payload: dict) -> None:
        self.messages.append(payload)


def tool_step(name: str, arguments: dict) -> ProviderChunk:
    return ProviderChunk(
        tool_calls=(ToolCall(name=name, arguments=arguments),),
        done=True,
        finish_reason="tool_calls",
    )


def final_step(text: str = "done") -> ProviderChunk:
    return ProviderChunk(
        content=text,
        done=True,
        finish_reason="stop",
    )


class ScriptedProvider:
    provider_name = "fake"
    preferred_model = "fake-model"
    context_window = 32768

    def __init__(self, steps: list[ProviderChunk]) -> None:
        self.steps = list(steps)
        self.calls = 0

    async def stream_chat(
        self,
        *,
        model: str,
        messages: list[dict],
        tools: list[dict] | None = None,
    ) -> AsyncIterator[ProviderChunk]:
        if self.calls >= len(self.steps):
            raise AssertionError("Provider called more times than scripted.")
        chunk = self.steps[self.calls]
        self.calls += 1
        yield chunk


class RetryThenPatchProvider:
    provider_name = "fake"
    preferred_model = "fake-model"
    context_window = 32768

    def __init__(self) -> None:
        self.calls = 0

    async def stream_chat(
        self,
        *,
        model: str,
        messages: list[dict],
        tools: list[dict] | None = None,
    ) -> AsyncIterator[ProviderChunk]:
        self.calls += 1
        if self.calls == 1:
            raise ProviderError(
                "TRANSIENT_TEST",
                "temporary failure",
                transient=True,
            )
        if self.calls == 2:
            yield tool_step(
                "apply_patch",
                {
                    "path": "value.txt",
                    "old_text": "before",
                    "new_text": "after",
                },
            )
            return
        yield final_step("patched once")


class BlockingProvider:
    provider_name = "fake"
    preferred_model = "fake-model"
    context_window = 32768

    def __init__(self) -> None:
        self.started = asyncio.Event()

    async def stream_chat(
        self,
        *,
        model: str,
        messages: list[dict],
        tools: list[dict] | None = None,
    ) -> AsyncIterator[ProviderChunk]:
        self.started.set()
        await asyncio.sleep(3600)
        yield final_step("unreachable")


def failed_event(ws: FakeWebSocket) -> dict | None:
    for event in reversed(ws.messages):
        if event.get("type") == "turn.failed":
            return event
    return None


class AgentReliabilityTests(unittest.IsolatedAsyncioTestCase):
    async def test_short_ab_cycle_stops_turn(self) -> None:
        with tempfile.TemporaryDirectory() as data_root, tempfile.TemporaryDirectory() as repo_root:
            Path(repo_root, "README.md").write_text("hello", encoding="utf-8")
            provider = ScriptedProvider(
                [
                    tool_step("read_file", {"path": "README.md"}),
                    tool_step("file_exists", {"path": "README.md"}),
                    tool_step("read_file", {"path": "README.md"}),
                    tool_step("file_exists", {"path": "README.md"}),
                ]
            )
            with patch.dict(os.environ, {"LCA_DATA_DIR": data_root}):
                server = AgentServer("test-token")
                server.provider = provider
                project, thread, _ = server.projects.open(
                    repo_root,
                    active_model="fake-model",
                )
                ws = FakeWebSocket()
                try:
                    await server.run_tool_turn(
                        ws,
                        thread_id=thread.id,
                        turn_id="turn_cycle",
                        prompt="inspect repeatedly",
                        model="fake-model",
                    )
                finally:
                    server.close()

            event = failed_event(ws)
            self.assertIsNotNone(event)
            assert event is not None
            self.assertEqual(event["payload"]["code"], "TOOL_LOOP_DETECTED")
            self.assertEqual(event["payload"]["loop_reason"], "short_cycle")
            cycle_results = [
                item
                for item in ws.messages
                if item.get("type") == "tool.completed"
                and item.get("payload", {})
                .get("result", {})
                .get("error", {})
                .get("code") == "REPEATED_TOOL_CYCLE"
            ]
            self.assertEqual(len(cycle_results), 1)

    async def test_consecutive_tool_failures_stop_turn(self) -> None:
        with tempfile.TemporaryDirectory() as data_root, tempfile.TemporaryDirectory() as repo_root:
            provider = ScriptedProvider(
                [
                    tool_step("run_command", {"command": "echo one"}),
                    tool_step(
                        "write_file",
                        {"path": "a.txt", "content": "x"},
                    ),
                    tool_step(
                        "apply_patch",
                        {
                            "path": "a.txt",
                            "old_text": "x",
                            "new_text": "y",
                        },
                    ),
                ]
            )
            with patch.dict(os.environ, {"LCA_DATA_DIR": data_root}):
                server = AgentServer("test-token")
                server.provider = provider
                server.permissions.set_mode(PermissionMode.READ_ONLY)
                server.max_consecutive_tool_failures = 3
                project, thread, _ = server.projects.open(
                    repo_root,
                    active_model="fake-model",
                )
                ws = FakeWebSocket()
                try:
                    await server.run_tool_turn(
                        ws,
                        thread_id=thread.id,
                        turn_id="turn_failures",
                        prompt="keep trying forbidden writes",
                        model="fake-model",
                    )
                finally:
                    server.close()

            event = failed_event(ws)
            self.assertIsNotNone(event)
            assert event is not None
            self.assertEqual(event["payload"]["code"], "TOOL_FAILURE_LIMIT")
            self.assertEqual(event["payload"]["consecutive_failures"], 3)
            self.assertEqual(event["payload"]["last_failure_code"], "PERMISSION_DENIED")

    async def test_transient_model_retry_executes_patch_only_once(self) -> None:
        with tempfile.TemporaryDirectory() as data_root, tempfile.TemporaryDirectory() as repo_root:
            target = Path(repo_root, "value.txt")
            target.write_text("before", encoding="utf-8")
            provider = RetryThenPatchProvider()

            with patch.dict(os.environ, {"LCA_DATA_DIR": data_root}):
                server = AgentServer("test-token")
                server.provider = provider
                server.model_retry_attempts = 2
                project, thread, _ = server.projects.open(
                    repo_root,
                    active_model="fake-model",
                )
                ws = FakeWebSocket()
                try:
                    await server.run_tool_turn(
                        ws,
                        thread_id=thread.id,
                        turn_id="turn_retry",
                        prompt="patch the file",
                        model="fake-model",
                    )
                finally:
                    server.close()

            self.assertEqual(target.read_text(encoding="utf-8"), "after")
            patch_events = [
                item
                for item in ws.messages
                if item.get("type") == "tool.completed"
                and item.get("payload", {}).get("name") == "apply_patch"
            ]
            self.assertEqual(len(patch_events), 1)
            retry_events = [
                item
                for item in ws.messages
                if item.get("type") == "turn.status"
                and item.get("payload", {}).get("phase") == "model_retry"
            ]
            self.assertEqual(len(retry_events), 1)

    async def test_cancelled_turn_emits_cancelled_event(self) -> None:
        with tempfile.TemporaryDirectory() as data_root, tempfile.TemporaryDirectory() as repo_root:
            provider = BlockingProvider()
            with patch.dict(os.environ, {"LCA_DATA_DIR": data_root}):
                server = AgentServer("test-token")
                server.provider = provider
                project, thread, _ = server.projects.open(
                    repo_root,
                    active_model="fake-model",
                )
                ws = FakeWebSocket()
                task = asyncio.create_task(
                    server.run_tool_turn(
                        ws,
                        thread_id=thread.id,
                        turn_id="turn_cancel",
                        prompt="wait forever",
                        model="fake-model",
                    )
                )
                try:
                    await asyncio.wait_for(provider.started.wait(), timeout=2)
                    task.cancel()
                    with self.assertRaises(asyncio.CancelledError):
                        await task
                finally:
                    server.close()

            cancelled = [
                item
                for item in ws.messages
                if item.get("type") == "turn.cancelled"
            ]
            self.assertEqual(len(cancelled), 1)
            self.assertEqual(
                cancelled[0]["payload"]["reason"],
                "user_cancelled",
            )

    async def test_model_step_limit_is_enforced(self) -> None:
        with tempfile.TemporaryDirectory() as data_root, tempfile.TemporaryDirectory() as repo_root:
            Path(repo_root, "a.txt").write_text("a", encoding="utf-8")
            Path(repo_root, "b.txt").write_text("b", encoding="utf-8")
            provider = ScriptedProvider(
                [
                    tool_step("file_exists", {"path": "a.txt"}),
                    tool_step("file_exists", {"path": "b.txt"}),
                ]
            )
            with patch.dict(os.environ, {"LCA_DATA_DIR": data_root}):
                server = AgentServer("test-token")
                server.provider = provider
                server.max_model_steps = 2
                project, thread, _ = server.projects.open(
                    repo_root,
                    active_model="fake-model",
                )
                ws = FakeWebSocket()
                try:
                    await server.run_tool_turn(
                        ws,
                        thread_id=thread.id,
                        turn_id="turn_steps",
                        prompt="never finish",
                        model="fake-model",
                    )
                finally:
                    server.close()

            event = failed_event(ws)
            self.assertIsNotNone(event)
            assert event is not None
            self.assertEqual(event["payload"]["code"], "MAX_MODEL_STEPS")

    async def test_tool_call_limit_is_enforced(self) -> None:
        with tempfile.TemporaryDirectory() as data_root, tempfile.TemporaryDirectory() as repo_root:
            provider = ScriptedProvider(
                [
                    ProviderChunk(
                        tool_calls=(
                            ToolCall(name="file_exists", arguments={"path": "a"}),
                            ToolCall(name="file_exists", arguments={"path": "b"}),
                            ToolCall(name="file_exists", arguments={"path": "c"}),
                        ),
                        done=True,
                        finish_reason="tool_calls",
                    )
                ]
            )
            with patch.dict(os.environ, {"LCA_DATA_DIR": data_root}):
                server = AgentServer("test-token")
                server.provider = provider
                server.max_tool_calls = 2
                project, thread, _ = server.projects.open(
                    repo_root,
                    active_model="fake-model",
                )
                ws = FakeWebSocket()
                try:
                    await server.run_tool_turn(
                        ws,
                        thread_id=thread.id,
                        turn_id="turn_tools",
                        prompt="too many tools",
                        model="fake-model",
                    )
                finally:
                    server.close()

            event = failed_event(ws)
            self.assertIsNotNone(event)
            assert event is not None
            self.assertEqual(event["payload"]["code"], "MAX_TOOL_CALLS")
            self.assertEqual(event["payload"]["tool_calls"], 3)

    def test_limits_can_be_configured_from_environment(self) -> None:
        with tempfile.TemporaryDirectory() as data_root:
            with patch.dict(
                os.environ,
                {
                    "LCA_DATA_DIR": data_root,
                    "LCA_MAX_MODEL_STEPS": "7",
                    "LCA_MAX_TOOL_CALLS": "19",
                    "LCA_MAX_BLOCKED_REPEATS": "2",
                    "LCA_MAX_CONSECUTIVE_TOOL_FAILURES": "5",
                    "LCA_MODEL_RETRY_ATTEMPTS": "3",
                },
            ):
                server = AgentServer("test-token")
                try:
                    self.assertEqual(server.max_model_steps, 7)
                    self.assertEqual(server.max_tool_calls, 19)
                    self.assertEqual(server.max_blocked_repeats, 2)
                    self.assertEqual(server.max_consecutive_tool_failures, 5)
                    self.assertEqual(server.model_retry_attempts, 3)
                finally:
                    server.close()


if __name__ == "__main__":
    unittest.main()
