from __future__ import annotations

import os
import tempfile
import unittest
from collections.abc import AsyncIterator
from unittest.mock import patch

from agent.core.settings import RuntimeSettings
from agent.llm.base import ProviderChunk
from agent.persistence.store import SQLiteStore
from agent.server.main import AgentServer


class FakeWebSocket:
    def __init__(self) -> None:
        self.messages: list[dict] = []

    async def send_json(self, payload: dict) -> None:
        self.messages.append(payload)


class FakeProvider:
    provider_name = "openai_compatible"
    preferred_model = "coder-model"
    context_window = 65536

    async def list_models(self):
        return []

    async def get_status(self) -> dict:
        return {
            "provider": self.provider_name,
            "online": True,
            "base_url": "http://127.0.0.1:9999/v1",
            "models": [{"name": "coder-model"}],
            "default_model": "coder-model",
            "preferred_model": "coder-model",
            "context_window": self.context_window,
            "error": None,
        }

    async def stream_chat(
        self,
        *,
        model: str,
        messages: list[dict],
        tools: list[dict] | None = None,
    ) -> AsyncIterator[ProviderChunk]:
        yield ProviderChunk(content="ok", done=True)


class RuntimeSettingsTests(unittest.TestCase):
    def test_settings_round_trip_without_secret(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            store = SQLiteStore(root)
            settings = RuntimeSettings.validate(
                {
                    **RuntimeSettings.defaults().__dict__,
                    "provider": "openai_compatible",
                    "openai_base_url": "https://example.test/v1",
                    "openai_model": "coder-model",
                    "openai_context_window": 65536,
                    "max_model_steps": 21,
                    "context_reserved_output_tokens": 8192,
                }
            )
            settings.save(store)

            reopened = RuntimeSettings.load(store)
            self.assertEqual(reopened.provider, "openai_compatible")
            self.assertEqual(reopened.openai_model, "coder-model")
            self.assertEqual(reopened.openai_context_window, 65536)
            self.assertEqual(reopened.max_model_steps, 21)
            self.assertEqual(reopened.context_reserved_output_tokens, 8192)

            rows = store.connection.execute(
                "SELECT key, value FROM settings ORDER BY key"
            ).fetchall()
            serialized = str([(row["key"], row["value"]) for row in rows])
            self.assertNotIn("api_key", serialized.lower())
            self.assertNotIn("secret-value", serialized)
            store.close()

    def test_invalid_settings_are_rejected(self) -> None:
        base = RuntimeSettings.defaults().__dict__
        with self.assertRaises(ValueError):
            RuntimeSettings.validate(
                {**base, "openai_base_url": "not-a-url"}
            )
        with self.assertRaises(ValueError):
            RuntimeSettings.validate(
                {**base, "max_tool_calls": 0}
            )
        with self.assertRaises(ValueError):
            RuntimeSettings.validate(
                {**base, "ollama_temperature": 5}
            )


class RuntimeSettingsProtocolTests(unittest.IsolatedAsyncioTestCase):
    async def test_apply_and_secret_never_echo_secret(self) -> None:
        with tempfile.TemporaryDirectory() as data_root:
            with patch.dict(os.environ, {"LCA_DATA_DIR": data_root}, clear=False):
                server = AgentServer("test-token")
                ws = FakeWebSocket()
                try:
                    with patch.object(
                        RuntimeSettings,
                        "create_provider",
                        return_value=FakeProvider(),
                    ):
                        await server.handle_message(
                            ws,
                            {
                                "type": "settings.apply",
                                "request_id": "req_apply",
                                "payload": {
                                    "settings": {
                                        "provider": "openai_compatible",
                                        "openai_base_url": "http://127.0.0.1:9999/v1",
                                        "openai_model": "coder-model",
                                        "openai_context_window": 65536,
                                        "context_reserved_output_tokens": 8192,
                                    }
                                },
                            },
                            set(),
                        )
                        await server.handle_message(
                            ws,
                            {
                                "type": "settings.secret",
                                "request_id": "req_secret",
                                "payload": {
                                    "openai_api_key": "secret-value",
                                },
                            },
                            set(),
                        )
                        await server.handle_message(
                            ws,
                            {
                                "type": "settings.get",
                                "request_id": "req_get",
                                "payload": {},
                            },
                            set(),
                        )

                    changed = next(
                        item for item in ws.messages
                        if item["type"] == "settings.changed"
                    )
                    self.assertEqual(
                        changed["payload"]["provider"],
                        "openai_compatible",
                    )
                    self.assertEqual(
                        changed["payload"]["context_reserved_output_tokens"],
                        8192,
                    )

                    loaded = next(
                        item for item in reversed(ws.messages)
                        if item["type"] == "settings.loaded"
                    )
                    self.assertTrue(loaded["payload"]["api_key_configured"])
                    self.assertNotIn("openai_api_key", loaded["payload"])
                    self.assertNotIn("secret-value", str(ws.messages))

                    rows = server.store.connection.execute(
                        "SELECT key, value FROM settings"
                    ).fetchall()
                    self.assertNotIn(
                        "secret-value",
                        str([(row["key"], row["value"]) for row in rows]),
                    )
                finally:
                    server.close()

    async def test_settings_change_is_blocked_during_active_turn(self) -> None:
        with tempfile.TemporaryDirectory() as data_root:
            with patch.dict(os.environ, {"LCA_DATA_DIR": data_root}, clear=False):
                server = AgentServer("test-token")
                ws = FakeWebSocket()

                async def pending() -> None:
                    import asyncio
                    await asyncio.sleep(60)

                import asyncio
                task = asyncio.create_task(pending())
                server.active_turns["turn_test"] = task
                try:
                    await server.handle_message(
                        ws,
                        {
                            "type": "settings.apply",
                            "request_id": "req_blocked",
                            "payload": {"settings": {"max_model_steps": 10}},
                        },
                        set(),
                    )
                    error = next(
                        item for item in ws.messages
                        if item["type"] == "error"
                    )
                    self.assertEqual(error["payload"]["code"], "TURN_RUNNING")
                finally:
                    task.cancel()
                    with self.assertRaises(asyncio.CancelledError):
                        await task
                    server.close()


if __name__ == "__main__":
    unittest.main()
