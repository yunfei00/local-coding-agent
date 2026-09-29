from __future__ import annotations

import os
import tempfile
import unittest
from collections.abc import AsyncIterator
from unittest.mock import patch

from agent.llm.base import ProviderChunk
from agent.server.main import AgentServer


class FakeWebSocket:
    def __init__(self) -> None:
        self.messages: list[dict] = []

    async def send_json(self, payload: dict) -> None:
        self.messages.append(payload)


class CaptureProvider:
    provider_name = "fake"
    preferred_model = "fake-model"
    context_window = 2048

    def __init__(self) -> None:
        self.seen_messages: list[list[dict]] = []

    async def stream_chat(
        self,
        *,
        model: str,
        messages: list[dict],
        tools: list[dict] | None = None,
    ) -> AsyncIterator[ProviderChunk]:
        self.seen_messages.append([dict(item) for item in messages])
        yield ProviderChunk(
            content="done",
            done=True,
            finish_reason="stop",
            prompt_eval_count=100,
            eval_count=10,
        )


class AgentContextIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def test_long_thread_is_bounded_and_reports_usage(self) -> None:
        with tempfile.TemporaryDirectory() as data_root, tempfile.TemporaryDirectory() as repo_root:
            with patch.dict(os.environ, {"LCA_DATA_DIR": data_root}):
                server = AgentServer("test-token")
                provider = CaptureProvider()
                server.provider = provider
                project, thread, _ = server.projects.open(
                    repo_root,
                    active_model="fake-model",
                )
                server.prompt_rules.set(
                    "global",
                    None,
                    "GLOBAL-RULE-MUST-STAY",
                )

                for index in range(30):
                    project.state.append_exchange(
                        thread.id,
                        user=f"old-user-{index}-" + ("u" * 700),
                        assistant=f"old-assistant-{index}-" + ("a" * 700),
                    )

                ws = FakeWebSocket()
                try:
                    await server.run_tool_turn(
                        ws,
                        thread_id=thread.id,
                        turn_id="turn_context",
                        prompt="LATEST-REQUEST",
                        model="fake-model",
                    )

                    sent = provider.seen_messages[0]
                    serialized = str(sent)
                    self.assertIn("GLOBAL-RULE-MUST-STAY", sent[0]["content"])
                    self.assertEqual(sent[-1]["content"], "LATEST-REQUEST")
                    self.assertIn("old-assistant-29-", serialized)
                    self.assertNotIn("old-user-0-", serialized)

                    context_events = [
                        event
                        for event in ws.messages
                        if event.get("type") == "context.updated"
                    ]
                    self.assertGreaterEqual(len(context_events), 1)
                    usage = context_events[-1]["payload"]
                    self.assertGreater(usage["omitted_history_messages"], 0)
                    self.assertLessEqual(
                        usage["estimated_input_tokens"],
                        usage["input_budget_tokens"],
                    )

                    completed = [
                        event
                        for event in ws.messages
                        if event.get("type") == "turn.completed"
                    ]
                    self.assertEqual(len(completed), 1)
                    self.assertEqual(
                        completed[0]["payload"]["context"]["context_window_tokens"],
                        2048,
                    )
                finally:
                    server.close()


if __name__ == "__main__":
    unittest.main()
