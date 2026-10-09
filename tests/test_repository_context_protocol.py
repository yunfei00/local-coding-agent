from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from agent.server.main import AgentServer


class FakeWebSocket:
    def __init__(self) -> None:
        self.messages: list[dict] = []

    async def send_json(self, payload: dict) -> None:
        self.messages.append(payload)


class RepositoryContextProtocolTests(unittest.IsolatedAsyncioTestCase):
    async def test_context_pin_refresh_get_and_unpin(self) -> None:
        with (
            tempfile.TemporaryDirectory() as data_root,
            tempfile.TemporaryDirectory() as workspace_root,
            patch.dict(os.environ, {"LCA_DATA_DIR": data_root}, clear=False),
        ):
            workspace = Path(workspace_root)
            source = workspace / "src"
            source.mkdir()
            (source / "app.py").write_text(
                "class App:\n    pass\n",
                encoding="utf-8",
            )

            server = AgentServer("token")
            ws = FakeWebSocket()
            owned: set[str] = set()
            try:
                project, thread, _ = server.projects.open(
                    workspace,
                    active_model="test-model",
                )

                await server.handle_message(
                    ws,
                    {
                        "type": "context.pin",
                        "request_id": "pin",
                        "thread_id": thread.id,
                        "payload": {
                            "thread_id": thread.id,
                            "path": "src/app.py",
                        },
                    },
                    owned,
                )
                changed = ws.messages[-1]
                self.assertEqual(changed["type"], "context.changed")
                self.assertEqual(
                    changed["payload"]["pinned"][0]["path"],
                    "src/app.py",
                )
                self.assertEqual(
                    changed["payload"]["pinned"][0]["status"],
                    "ready",
                )

                await server.handle_message(
                    ws,
                    {
                        "type": "context.get",
                        "request_id": "get",
                        "thread_id": thread.id,
                        "payload": {"thread_id": thread.id},
                    },
                    owned,
                )
                loaded = ws.messages[-1]
                self.assertEqual(loaded["type"], "context.loaded")
                self.assertIn(
                    "src/app.py",
                    loaded["payload"]["repository_map"]["files"],
                )

                (source / "app.py").write_text(
                    "class App:\n    pass\n\ndef build():\n    return 1\n",
                    encoding="utf-8",
                )
                await server.handle_message(
                    ws,
                    {
                        "type": "context.refresh",
                        "request_id": "refresh",
                        "thread_id": thread.id,
                        "payload": {"thread_id": thread.id},
                    },
                    owned,
                )
                refreshed = ws.messages[-1]
                self.assertEqual(refreshed["type"], "context.changed")
                self.assertGreaterEqual(
                    refreshed["payload"]["repository_map"]["revision"],
                    2,
                )

                (source / "app.py").unlink()
                await server.handle_message(
                    ws,
                    {
                        "type": "context.get",
                        "request_id": "missing",
                        "thread_id": thread.id,
                        "payload": {"thread_id": thread.id},
                    },
                    owned,
                )
                missing = ws.messages[-1]
                self.assertEqual(
                    missing["payload"]["pinned"][0]["status"],
                    "missing",
                )

                await server.handle_message(
                    ws,
                    {
                        "type": "context.unpin",
                        "request_id": "unpin",
                        "thread_id": thread.id,
                        "payload": {
                            "thread_id": thread.id,
                            "path": "src/app.py",
                        },
                    },
                    owned,
                )
                unpinned = ws.messages[-1]
                self.assertEqual(unpinned["type"], "context.changed")
                self.assertEqual(unpinned["payload"]["pinned"], [])
                self.assertEqual(
                    server.store.list_pinned_context(thread.id),
                    [],
                )
                self.assertEqual(server.projects.active.id, project.id)
            finally:
                await server.close_async()
                server.close()


if __name__ == "__main__":
    unittest.main()
