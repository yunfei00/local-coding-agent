from __future__ import annotations

import os
import subprocess
import tempfile
import unittest
from collections.abc import AsyncIterator
from pathlib import Path
from unittest.mock import patch

from agent.llm.base import ProviderChunk, ToolCall
from agent.server.main import AgentServer


class FakeWebSocket:
    def __init__(self) -> None:
        self.messages: list[dict] = []

    async def send_json(self, payload: dict) -> None:
        self.messages.append(payload)


class ScriptedProvider:
    provider_name = "fake"
    context_window = 32768

    def __init__(self, steps: list[ProviderChunk]) -> None:
        self.steps = list(steps)
        self.calls = 0
        self.seen_messages: list[list[dict]] = []

    async def stream_chat(
        self,
        *,
        model: str,
        messages: list[dict],
        tools: list[dict] | None = None,
    ) -> AsyncIterator[ProviderChunk]:
        self.seen_messages.append([dict(item) for item in messages])
        if self.calls >= len(self.steps):
            raise AssertionError("Fake provider was called more times than scripted.")
        chunk = self.steps[self.calls]
        self.calls += 1
        yield chunk


def tool_step(name: str, arguments: dict) -> ProviderChunk:
    return ProviderChunk(
        tool_calls=(ToolCall(name=name, arguments=arguments),),
        done=True,
        finish_reason="tool_calls",
    )


def final_step(text: str) -> ProviderChunk:
    return ProviderChunk(
        content=text,
        done=True,
        finish_reason="stop",
        prompt_eval_count=100,
        eval_count=20,
    )


def init_git_repo(root: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    subprocess.run(
        ["git", "config", "user.email", "phase8@example.test"],
        cwd=root,
        check=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Phase 8"],
        cwd=root,
        check=True,
    )


def commit_all(root: Path, message: str = "fixture") -> None:
    subprocess.run(["git", "add", "."], cwd=root, check=True)
    subprocess.run(
        ["git", "commit", "-q", "-m", message],
        cwd=root,
        check=True,
    )


def tool_completed_events(ws: FakeWebSocket, name: str) -> list[dict]:
    return [
        event
        for event in ws.messages
        if event.get("type") == "tool.completed"
        and event.get("payload", {}).get("name") == name
    ]


class AgentE2ETests(unittest.IsolatedAsyncioTestCase):
    async def test_python_failure_fix_retest_diff_loop(self) -> None:
        with tempfile.TemporaryDirectory() as data_root, tempfile.TemporaryDirectory() as repo_root:
            repo = Path(repo_root)
            init_git_repo(repo)
            (repo / "calculator.py").write_text(
                "def add(a, b):\n    return a - b\n",
                encoding="utf-8",
            )
            (repo / "test_calculator.py").write_text(
                "import unittest\n"
                "from calculator import add\n\n"
                "class CalculatorTests(unittest.TestCase):\n"
                "    def test_add(self):\n"
                "        self.assertEqual(add(2, 3), 5)\n\n"
                "if __name__ == '__main__':\n"
                "    unittest.main()\n",
                encoding="utf-8",
            )
            commit_all(repo)

            steps = [
                tool_step("file_exists", {"path": "test_calculator.py"}),
                tool_step(
                    "run_command",
                    {
                        "command": "python -m unittest discover -q",
                        "timeout_seconds": 30,
                    },
                ),
                tool_step("read_file", {"path": "calculator.py"}),
                tool_step(
                    "apply_patch",
                    {
                        "path": "calculator.py",
                        "old_text": "return a - b",
                        "new_text": "return a + b",
                    },
                ),
                tool_step(
                    "run_command",
                    {
                        "command": "python -m unittest discover -q",
                        "timeout_seconds": 30,
                    },
                ),
                tool_step("git_diff", {}),
                final_step(
                    "Fixed calculator.add, reran the real unit tests successfully, "
                    "and inspected the final Git diff."
                ),
            ]

            with patch.dict(os.environ, {"LCA_DATA_DIR": data_root}):
                server = AgentServer("test-token")
                provider = ScriptedProvider(steps)
                server.provider = provider
                project, thread, _ = server.projects.open(
                    repo,
                    active_model="fake-model",
                )
                ws = FakeWebSocket()

                try:
                    await server.run_tool_turn(
                        ws,
                        thread_id=thread.id,
                        turn_id="turn_python_e2e",
                        prompt="Run the failing tests and fix the bug until they pass.",
                        model="fake-model",
                    )

                    command_events = tool_completed_events(ws, "run_command")
                    self.assertEqual(len(command_events), 2)
                    self.assertNotEqual(
                        command_events[0]["payload"]["result"]["exit_code"],
                        0,
                    )
                    self.assertEqual(
                        command_events[1]["payload"]["result"]["exit_code"],
                        0,
                    )

                    diff_events = tool_completed_events(ws, "git_diff")
                    self.assertEqual(len(diff_events), 1)
                    diff_result = diff_events[0]["payload"]["result"]
                    self.assertTrue(diff_result["ok"])
                    self.assertEqual(diff_result["data"]["file_count"], 1)
                    self.assertEqual(
                        diff_result["data"]["files"][0]["path"],
                        "calculator.py",
                    )

                    self.assertIn(
                        "return a + b",
                        (repo / "calculator.py").read_text(encoding="utf-8"),
                    )

                    completed = [
                        event
                        for event in ws.messages
                        if event.get("type") == "turn.completed"
                    ]
                    self.assertEqual(len(completed), 1)
                    verification = completed[0]["payload"]["verification"]
                    self.assertTrue(verification["complete"])
                    self.assertEqual(verification["missing"], [])

                    stored = project.state.get_messages(thread.id)
                    self.assertEqual(stored[0]["role"], "user")
                    self.assertEqual(stored[-1]["role"], "assistant")
                    self.assertIn("reran the real unit tests", stored[-1]["content"])

                    # Confirm real tool failures/results were fed back into later model calls.
                    serialized = str(provider.seen_messages)
                    self.assertIn("'exit_code': 1", serialized)
                    self.assertIn("'exit_code': 0", serialized)
                finally:
                    server.close()

    async def test_node_failure_fix_retest_diff_loop(self) -> None:
        with tempfile.TemporaryDirectory() as data_root, tempfile.TemporaryDirectory() as repo_root:
            repo = Path(repo_root)
            init_git_repo(repo)
            (repo / "math.cjs").write_text(
                "exports.add = (a, b) => a - b;\n",
                encoding="utf-8",
            )
            (repo / "math.test.cjs").write_text(
                "const test = require('node:test');\n"
                "const assert = require('node:assert/strict');\n"
                "const { add } = require('./math.cjs');\n\n"
                "test('add', () => {\n"
                "  assert.equal(add(4, 5), 9);\n"
                "});\n",
                encoding="utf-8",
            )
            (repo / "package.json").write_text(
                '{"name":"phase8-node-fixture","private":true,"scripts":{"test":"node --test math.test.cjs"}}\n',
                encoding="utf-8",
            )
            commit_all(repo)

            steps = [
                tool_step("file_exists", {"path": "package.json"}),
                tool_step(
                    "run_command",
                    {"command": "npm test", "timeout_seconds": 30},
                ),
                tool_step("read_file", {"path": "math.cjs"}),
                tool_step(
                    "apply_patch",
                    {
                        "path": "math.cjs",
                        "old_text": "a - b",
                        "new_text": "a + b",
                    },
                ),
                tool_step(
                    "run_command",
                    {"command": "npm test", "timeout_seconds": 30},
                ),
                tool_step("git_diff", {}),
                final_step(
                    "Fixed the Node bug, reran npm test successfully, and reviewed the diff."
                ),
            ]

            with patch.dict(os.environ, {"LCA_DATA_DIR": data_root}):
                server = AgentServer("test-token")
                provider = ScriptedProvider(steps)
                server.provider = provider
                project, thread, _ = server.projects.open(
                    repo,
                    active_model="fake-model",
                )
                ws = FakeWebSocket()

                try:
                    await server.run_tool_turn(
                        ws,
                        thread_id=thread.id,
                        turn_id="turn_node_e2e",
                        prompt="Run the Node tests, fix the failure, retest, and review the diff.",
                        model="fake-model",
                    )

                    command_events = tool_completed_events(ws, "run_command")
                    self.assertEqual(len(command_events), 2)
                    self.assertNotEqual(
                        command_events[0]["payload"]["result"]["exit_code"],
                        0,
                    )
                    self.assertEqual(
                        command_events[1]["payload"]["result"]["exit_code"],
                        0,
                    )
                    self.assertIn(
                        "a + b",
                        (repo / "math.cjs").read_text(encoding="utf-8"),
                    )

                    completed = [
                        event
                        for event in ws.messages
                        if event.get("type") == "turn.completed"
                    ]
                    self.assertEqual(len(completed), 1)
                    self.assertTrue(
                        completed[0]["payload"]["verification"]["complete"]
                    )
                finally:
                    server.close()


if __name__ == "__main__":
    unittest.main()
