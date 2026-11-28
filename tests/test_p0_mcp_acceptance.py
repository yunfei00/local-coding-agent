from __future__ import annotations

import asyncio
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

from agent.mcp.runtime import MCPRuntime
from agent.mcp.settings import MCPSettingsManager
from agent.persistence.store import SQLiteStore
from agent.server.projects import ProjectRegistry


class _DummyProjects(ProjectRegistry):
    def __init__(self):
        self._projects = []
    def list_projects(self):
        return []
    def get(self, pid):
        return None


class P0McpAcceptanceTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.db = self.root / "test.sqlite3"
        self.store = SQLiteStore(self.db)
        self.settings = MCPSettingsManager(self.store)
        self.runtime = MCPRuntime(self.settings, _DummyProjects())
        self.mcp_root = self.root / "mcp-root"
        self.server_script = str(Path(__file__).resolve().parents[1] / "tests" / "mcp_test_server.py")

    async def asyncTearDown(self):
        try:
            await self.runtime.close()
        except Exception:
            pass
        try:
            self.store.close()
        except Exception:
            pass
        try:
            self.tmp.cleanup()
        except Exception:
            pass

    def _cfg(self, **overrides):
        base = {
            "name": "test-server",
            "transport": "stdio",
            "command": sys.executable,
            "args": [self.server_script, "--root", str(self.mcp_root)],
            "enabled": True,
            "trusted": False,
            "timeout_seconds": 30,
            "server_permission": "ask",
            "tool_permissions": {},
        }
        base.update(overrides)
        return base

    async def test_connect_discover_call_history_disable_reconnect(self):
        self.settings.upsert(self._cfg())
        await self.runtime.refresh()
        payload = self.runtime.public_payload()
        self.assertEqual(payload["connected_count"], 1)
        tools = payload["servers"][0]["tools"]
        names = {t["remote_tool"] for t in tools}
        self.assertIn("ping", names)
        self.assertIn("long_running", names)

        # call through adapter
        adapters = {a.remote_name: a for a in self.runtime.adapters}
        res = await adapters["echo"].execute({"text": "hi", "extra": {"a": 1}})
        self.assertTrue(res.ok)

        history = self.runtime.get_call_history()
        self.assertTrue(any(h.get("tool") == "echo" and h.get("status") == "completed" for h in history))

        # disable
        srv = self.settings.list()[0]
        self.settings.upsert({**self._cfg(), "id": srv.id, "enabled": False})
        await self.runtime.refresh()
        self.assertEqual(self.runtime.public_payload()["connected_count"], 0)

        # re-enable and reconnect
        self.settings.upsert({**self._cfg(), "id": srv.id, "enabled": True})
        await self.runtime.refresh()
        self.assertEqual(self.runtime.public_payload()["connected_count"], 1)

    async def test_permission_override_deny_blocks_adapter_metadata(self):
        self.settings.upsert(self._cfg(server_permission="deny"))
        await self.runtime.refresh()
        adapters = list(self.runtime.adapters)
        self.assertTrue(adapters)
        self.assertTrue(all(a.permission_metadata().get("permission_override") == "deny" for a in adapters))

    async def test_restart_persistence(self):
        srv = self.settings.upsert(self._cfg(name="persisted"))
        await self.runtime.refresh()
        self.assertEqual(self.runtime.public_payload()["connected_count"], 1)
        await self.runtime.close()
        self.store.close()

        # reopen
        store2 = SQLiteStore(self.db)
        try:
            settings2 = MCPSettingsManager(store2)
            runtime2 = MCPRuntime(settings2, _DummyProjects())
            try:
                await runtime2.refresh()
                payload = runtime2.public_payload()
                self.assertEqual(payload["server_count"], 1)
                self.assertEqual(payload["servers"][0]["name"], "persisted")
                self.assertEqual(payload["connected_count"], 1)
            finally:
                await runtime2.close()
        finally:
            store2.close()
        # prevent tearDown double-close
        self.store = SQLiteStore(self.db)

    async def test_long_running_cancel_records_cancelled(self):
        self.settings.upsert(self._cfg())
        await self.runtime.refresh()
        adapters = {a.remote_name: a for a in self.runtime.adapters}
        task = asyncio.create_task(adapters["long_running"].execute({"seconds": 30, "tick_ms": 100}))
        await asyncio.sleep(0.5)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        history = self.runtime.get_call_history()
        m = [h for h in history if h.get("tool") == "long_running" and h.get("status") == "cancelled"]
        self.assertTrue(m)
        self.assertIn("cancel", str(m[-1].get("cancel_note","")).lower())


if __name__ == "__main__":
    unittest.main()
