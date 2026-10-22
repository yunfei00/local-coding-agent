"""Chat uses the displayed model, even when the restored thread stores an old one."""
import asyncio
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from agent.server.main import AgentServer
from test_agent_reliability import FakeWebSocket, ScriptedProvider, final_step


class ChatProvider(ScriptedProvider):
    provider_name = "ollama"
    preferred_model = "gpt-oss:20b"

    def __init__(self):
        super().__init__([final_step("hello from selected model")])
        self.models_used = []
        self.online = True

    async def get_status(self):
        return {"online":self.online, "models":[{"name":self.preferred_model}],
                "error":None if self.online else {"code":"OLLAMA_UNAVAILABLE", "message":"Ollama is offline"}}

    async def stream_chat(self, *, model, messages, tools=None):
        self.models_used.append(model)
        async for chunk in super().stream_chat(model=model, messages=messages, tools=tools):
            yield chunk


class ChatModelSelectionTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.env = patch.dict(os.environ, {"LCA_DATA_DIR":str(self.root / "data")})
        self.env.start()
        self.server = AgentServer("test")
        self.provider = ChatProvider()
        self.server.provider = self.provider
        self.project, self.thread, _ = self.server.projects.open(self.root, active_model="DeepSeek-V4-Flash-SaaS")
        self.ws = FakeWebSocket()

    async def asyncTearDown(self):
        for task in list(self.server.active_turns.values()):
            task.cancel()
        await asyncio.gather(*list(self.server.active_turns.values()), return_exceptions=True)
        await self.server.close_async()
        self.server.close()
        self.env.stop()
        self.temp.cleanup()

    async def start(self, **payload):
        await self.server.handle_message(self.ws, {"type":"turn.start", "thread_id":self.thread.id,
            "payload":{"prompt":"hello", **payload}}, set())
        await asyncio.gather(*list(self.server.active_turns.values()))

    async def test_displayed_model_overrides_stale_thread_and_survives_restart(self):
        await self.start(model="gpt-oss:20b")
        self.assertEqual(self.provider.models_used, ["gpt-oss:20b"])
        self.assertEqual(self.thread.active_model, "gpt-oss:20b")
        started = next(e for e in self.ws.messages if e["type"] == "turn.started")
        self.assertEqual(started["payload"]["model"], "gpt-oss:20b")
        self.assertTrue(any(e["type"] == "model.selected" for e in self.ws.messages))
        self.assertTrue(any(e["type"] == "turn.completed" for e in self.ws.messages))
        self.assertTrue(self.project.state.get_messages(self.thread.id))
        await self.server.close_async()
        self.server.close()
        self.server = AgentServer("test")
        restored, thread, _ = self.server.projects.open(self.root, active_model="old-default")
        self.assertEqual(thread.id, self.thread.id)
        self.assertEqual(thread.active_model, "gpt-oss:20b")
        self.assertTrue(restored.state.get_messages(thread.id))

    async def test_legacy_client_without_model_keeps_thread_choice(self):
        self.project.state.set_thread_model(self.thread.id, "gpt-oss:20b")
        await self.start()
        self.assertEqual(self.provider.models_used, ["gpt-oss:20b"])

    async def test_invalid_explicit_model_does_not_fallback_or_change_thread(self):
        self.project.state.set_thread_model(self.thread.id, "gpt-oss:20b")
        await self.start(model="missing-api-model")
        self.assertEqual(self.ws.messages[-1]["payload"]["code"], "MODEL_NOT_FOUND")
        self.assertEqual(self.thread.active_model, "gpt-oss:20b")
        self.assertEqual(self.provider.models_used, [])
        self.assertFalse(self.project.state.get_messages(self.thread.id))

    async def test_empty_or_non_string_model_is_rejected_without_call(self):
        for model in ("", "  ", 42, [], {}):
            with self.subTest(model=model):
                await self.start(model=model)
                self.assertEqual(self.ws.messages[-1]["payload"]["code"], "MODEL_REQUIRED")
        self.assertEqual(self.provider.models_used, [])
        self.assertEqual(self.thread.active_model, "DeepSeek-V4-Flash-SaaS")

    async def test_provider_unavailable_keeps_previous_model_and_history(self):
        self.provider.online = False
        await self.start(model="gpt-oss:20b")
        self.assertEqual(self.ws.messages[-1]["payload"]["code"], "OLLAMA_UNAVAILABLE")
        self.assertEqual(self.thread.active_model, "DeepSeek-V4-Flash-SaaS")
        self.assertEqual(self.provider.models_used, [])

    async def test_running_turn_blocks_model_change_and_new_request(self):
        running = asyncio.create_task(asyncio.Event().wait())
        self.server.active_turns["running"] = running
        try:
            await self.server.handle_message(self.ws, {"type":"turn.start", "thread_id":self.thread.id,
                "payload":{"prompt":"hello", "model":"gpt-oss:20b"}}, set())
            self.assertEqual(self.ws.messages[-1]["payload"]["code"], "TURN_RUNNING")
            self.assertEqual(self.thread.active_model, "DeepSeek-V4-Flash-SaaS")
            self.assertEqual(self.provider.models_used, [])
        finally:
            running.cancel()
            await asyncio.gather(running, return_exceptions=True)
            self.server.active_turns.clear()
