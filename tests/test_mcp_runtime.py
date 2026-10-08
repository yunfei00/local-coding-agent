from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from agent.mcp.runtime import MCPRuntime
from agent.mcp.settings import MCPSettingsManager
from agent.persistence.store import SQLiteStore
from agent.server.projects import ProjectRegistry


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "mcp_test_server.py"


class MCPRuntimeTests(unittest.IsolatedAsyncioTestCase):
    async def test_runtime_registers_tools_and_never_exposes_secret_values(self) -> None:
        with (
            tempfile.TemporaryDirectory() as data_root,
            tempfile.TemporaryDirectory() as project_root,
        ):
            store = SQLiteStore(data_root)
            projects = ProjectRegistry(store)
            project, _, _ = projects.open(
                project_root,
                active_model="test-model",
            )
            settings = MCPSettingsManager(store)
            item = settings.upsert(
                {
                    "name": "runtime-test",
                    "transport": "stdio",
                    "command": sys.executable,
                    "args": [str(FIXTURE)],
                    "secret_env_keys": ["TOKEN"],
                    "enabled": True,
                    "trusted": True,
                    "timeout_seconds": 15,
                }
            )
            runtime = MCPRuntime(settings, projects)
            runtime.set_secrets(
                {
                    item.id: {
                        "TOKEN": "MCP-SHOULD-NOT-LEAK",
                    }
                }
            )
            try:
                await runtime.refresh()
                payload = runtime.public_payload()
                serialized = json.dumps(payload, ensure_ascii=False)

                self.assertEqual(payload["server_count"], 1)
                self.assertEqual(payload["connected_count"], 1)
                self.assertEqual(payload["tool_count"], 2)
                self.assertNotIn("MCP-SHOULD-NOT-LEAK", serialized)
                self.assertTrue(payload["servers"][0]["secret_configured"])

                names = project.tools.names
                self.assertIn(
                    "mcp__runtime-test__echo",
                    names,
                )
                metadata = project.tools.permission_metadata(
                    "mcp__runtime-test__echo"
                )
                self.assertEqual(metadata["source"], "mcp")
                self.assertTrue(metadata["trusted"])
                self.assertFalse(metadata["read_only"])
            finally:
                await runtime.close()
                store.close()

    async def test_disabled_server_is_not_connected_or_registered(self) -> None:
        with (
            tempfile.TemporaryDirectory() as data_root,
            tempfile.TemporaryDirectory() as project_root,
        ):
            store = SQLiteStore(data_root)
            projects = ProjectRegistry(store)
            project, _, _ = projects.open(
                project_root,
                active_model="test-model",
            )
            settings = MCPSettingsManager(store)
            settings.upsert(
                {
                    "name": "disabled",
                    "transport": "stdio",
                    "command": sys.executable,
                    "args": [str(FIXTURE)],
                    "enabled": False,
                    "trusted": True,
                }
            )
            runtime = MCPRuntime(settings, projects)
            try:
                await runtime.refresh()
                payload = runtime.public_payload()
                self.assertEqual(payload["enabled_count"], 0)
                self.assertEqual(payload["connected_count"], 0)
                self.assertEqual(payload["tool_count"], 0)
                self.assertFalse(
                    any(name.startswith("mcp__") for name in project.tools.names)
                )
            finally:
                await runtime.close()
                store.close()


if __name__ == "__main__":
    unittest.main()
