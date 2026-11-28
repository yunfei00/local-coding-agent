from __future__ import annotations

import asyncio
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

from agent.mcp.runtime import MCPRuntime
from agent.mcp.settings import MCPSettingsManager
from agent.permissions.approval import (
    APPROVAL_ALLOW_ONCE,
    APPROVAL_ALLOW_TURN,
    APPROVAL_DENY,
    ApprovalManager,
)
from agent.permissions.policy import PermissionMode, PermissionPolicy
from agent.persistence.store import SQLiteStore
from agent.tools.workspace import Workspace


class DummyWS:
    def __init__(self):
        self.messages = []

    async def send_json(self, payload):
        self.messages.append(payload)


class _DummyProjects:
    def list_projects(self):
        return []


class ApprovalCancelChainTests(unittest.IsolatedAsyncioTestCase):
    async def test_allow_once_allow_turn_deny_and_cancel_pending(self):
        mgr = ApprovalManager()
        ws = DummyWS()

        # allow_once
        t1 = asyncio.create_task(mgr.request(ws, turn_id="t1", thread_id="th", approval_key="k1", tool_name="run_command", arguments={"command": "echo hi"}, reason="r", risk="normal"))
        await asyncio.sleep(0)
        pending = next(iter(mgr._pending.values()))
        self.assertEqual(pending.tool_name, "run_command")
        mgr.respond(pending.id, APPROVAL_ALLOW_ONCE)
        self.assertEqual(await t1, APPROVAL_ALLOW_ONCE)
        self.assertFalse(mgr.is_granted_for_turn("t1", "k1"))

        # allow_turn caches for same turn/key
        t2 = asyncio.create_task(mgr.request(ws, turn_id="t1", thread_id="th", approval_key="k1", tool_name="run_command", arguments={"command": "echo hi"}, reason="r", risk="normal"))
        await asyncio.sleep(0)
        pending2 = next(iter(mgr._pending.values()))
        mgr.respond(pending2.id, APPROVAL_ALLOW_TURN)
        self.assertEqual(await t2, APPROVAL_ALLOW_TURN)
        self.assertTrue(mgr.is_granted_for_turn("t1", "k1"))
        # subsequent request auto-granted without pending approval
        res = await mgr.request(ws, turn_id="t1", thread_id="th", approval_key="k1", tool_name="run_command", arguments={"command": "echo hi"}, reason="r", risk="normal")
        self.assertEqual(res, APPROVAL_ALLOW_TURN)

        # deny
        t3 = asyncio.create_task(mgr.request(ws, turn_id="t2", thread_id="th", approval_key="k2", tool_name="write_file", arguments={}, reason="r", risk="normal"))
        await asyncio.sleep(0)
        pending3 = next(iter(mgr._pending.values()))
        mgr.respond(pending3.id, APPROVAL_DENY)
        self.assertEqual(await t3, APPROVAL_DENY)

        # cancel pending approval
        t4 = asyncio.create_task(mgr.request(ws, turn_id="t3", thread_id="th", approval_key="k3", tool_name="write_file", arguments={}, reason="r", risk="normal"))
        await asyncio.sleep(0)
        pending4 = next(iter(mgr._pending.values()))
        mgr.cancel(pending4.id)
        with self.assertRaises(asyncio.CancelledError):
            await t4

        # cancel_turn clears grants and pending
        t5 = asyncio.create_task(mgr.request(ws, turn_id="t1", thread_id="th", approval_key="k9", tool_name="write_file", arguments={}, reason="r", risk="normal"))
        await asyncio.sleep(0)
        mgr.cancel_turn("t1")
        self.assertFalse(mgr.is_granted_for_turn("t1", "k1"))
        with self.assertRaises(asyncio.CancelledError):
            await t5


class MCPPersistentPermissionTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.store = SQLiteStore(self.root / "test.sqlite3")
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
        self.tmp.cleanup()

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

    async def test_revoke_saved_permission_persists_after_refresh(self):
        srv = self.settings.upsert(self._cfg(server_permission="allow"))
        await self.runtime.refresh()
        adapters = list(self.runtime.adapters)
        self.assertTrue(adapters)
        self.assertTrue(all(a.permission_metadata().get("permission_override") == "allow" for a in adapters))

        # revoke saved permission
        self.settings.upsert({**self._cfg(), "id": srv.id, "server_permission": "deny"})
        await self.runtime.refresh()
        adapters = list(self.runtime.adapters)
        self.assertTrue(all(a.permission_metadata().get("permission_override") == "deny" for a in adapters))

        # restart persistence
        await self.runtime.close()
        self.store.close()
        store2 = SQLiteStore(self.root / "test.sqlite3")
        try:
            settings2 = MCPSettingsManager(store2)
            runtime2 = MCPRuntime(settings2, _DummyProjects())
            try:
                await runtime2.refresh()
                adapters2 = list(runtime2.adapters)
                self.assertTrue(adapters2)
                self.assertTrue(all(a.permission_metadata().get("permission_override") == "deny" for a in adapters2))
            finally:
                await runtime2.close()
        finally:
            store2.close()
        self.store = SQLiteStore(self.root / "test.sqlite3")

    async def test_mcp_cancel_note_recorded(self):
        self.settings.upsert(self._cfg())
        await self.runtime.refresh()
        adapters = {a.remote_name: a for a in self.runtime.adapters}
        task = asyncio.create_task(adapters["long_running"].execute({"seconds": 30, "tick_ms": 100}))
        await asyncio.sleep(0.5)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        history = self.runtime.get_call_history()
        cancelled = [h for h in history if h.get("tool") == "long_running" and h.get("status") == "cancelled"]
        self.assertTrue(cancelled)
        note = str(cancelled[-1].get("cancel_note", "")).lower()
        self.assertIn("cancel", note)
        self.assertTrue(any(k in note for k in ["not support", "not rolled back", "side effect"]))


class RestrictedBypassTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.ws = Workspace(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_restricted_blocks_all_mutating_and_external_paths(self):
        p = PermissionPolicy(PermissionMode.RESTRICTED)
        denied = [
            ("run_command", {"command": "echo hi"}),
            ("start_process", {"command": "python -V"}),
            ("write_file", {"path": "a.txt", "content": "x"}),
            ("delete_file", {"path": "a.txt"}),
            ("apply_patch", {"path": "a.txt", "patch": "*** Begin Patch\n*** End Patch"}),
            ("git_stage", {"paths": ["a"]}),
            ("git_commit", {"message": "x"}),
            ("desktop_click", {"window_id": "w", "selector": {"name": "x"}}),
            ("mcp__s__t", {}, {"source": "mcp", "server": "s", "trusted": False, "read_only": False, "risk": "mcp_mutating"}),
        ]
        for name, args, *meta in denied:
            md = meta[0] if meta else {}
            v = p.evaluate(tool_name=name, arguments=args, workspace=self.ws, tool_metadata=md)
            self.assertFalse(v.allowed, name)

    def test_restricted_allows_only_explicit_mcp_allow(self):
        p = PermissionPolicy(PermissionMode.RESTRICTED)
        meta = {"source": "mcp", "server": "s", "trusted": True, "read_only": True, "risk": "mcp_read_only", "permission_override": "allow"}
        self.assertTrue(p.evaluate(tool_name="mcp__s__t", arguments={}, workspace=self.ws, tool_metadata=meta).allowed)
        meta["permission_override"] = "ask"
        self.assertFalse(p.evaluate(tool_name="mcp__s__t", arguments={}, workspace=self.ws, tool_metadata=meta).allowed)
        meta["permission_override"] = "deny"
        self.assertFalse(p.evaluate(tool_name="mcp__s__t", arguments={}, workspace=self.ws, tool_metadata=meta).allowed)


if __name__ == "__main__":
    unittest.main()
