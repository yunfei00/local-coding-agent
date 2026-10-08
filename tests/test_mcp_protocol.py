from __future__ import annotations

import os
import tempfile
import unittest
from unittest.mock import patch

from agent.server.main import AgentServer


class FakeWebSocket:
    def __init__(self) -> None:
        self.messages: list[dict] = []

    async def send_json(self, payload: dict) -> None:
        self.messages.append(payload)


class MCPProtocolTests(unittest.IsolatedAsyncioTestCase):
    async def test_crud_secret_sync_and_diagnostics_are_sanitized(self) -> None:
        with (
            tempfile.TemporaryDirectory() as data_root,
            patch.dict(os.environ, {"LCA_DATA_DIR": data_root}, clear=False),
        ):
            server = AgentServer("token")
            ws = FakeWebSocket()
            owned: set[str] = set()
            try:
                await server.handle_message(
                    ws,
                    {
                        "type": "mcp.upsert",
                        "request_id": "req_upsert",
                        "payload": {
                            "server": {
                                "name": "disabled-test",
                                "transport": "stdio",
                                "command": "python",
                                "args": ["server.py"],
                                "secret_env_keys": ["TOKEN"],
                                "enabled": False,
                                "trusted": False,
                            }
                        },
                    },
                    owned,
                )
                changed = ws.messages[-1]
                self.assertEqual(changed["type"], "mcp.changed")
                servers = changed["payload"]["servers"]
                self.assertEqual(len(servers), 1)
                server_id = servers[0]["id"]

                await server.handle_message(
                    ws,
                    {
                        "type": "mcp.secrets",
                        "request_id": "req_secret",
                        "payload": {
                            "secrets": {
                                server_id: {
                                    "TOKEN": "MCP-PROTOCOL-SECRET",
                                }
                            }
                        },
                    },
                    owned,
                )
                self.assertEqual(ws.messages[-1]["type"], "mcp.changed")

                await server.handle_message(
                    ws,
                    {
                        "type": "mcp.list",
                        "request_id": "req_list",
                        "payload": {},
                    },
                    owned,
                )
                listed = ws.messages[-1]
                self.assertEqual(listed["type"], "mcp.listed")
                self.assertTrue(
                    listed["payload"]["servers"][0]["secret_configured"]
                )
                self.assertNotIn(
                    "MCP-PROTOCOL-SECRET",
                    str(listed),
                )

                server.mcp_runtime.last_errors[server_id] = (
                    "token=MCP-PROTOCOL-SECRET"
                )
                diagnostics = await server._diagnostics_payload()
                serialized = str(diagnostics)
                self.assertNotIn("MCP-PROTOCOL-SECRET", serialized)
                self.assertTrue(
                    diagnostics["redaction"]["mcp_credentials"]
                )

                await server.handle_message(
                    ws,
                    {
                        "type": "mcp.delete",
                        "request_id": "req_delete",
                        "payload": {"server_id": server_id},
                    },
                    owned,
                )
                self.assertEqual(ws.messages[-1]["type"], "mcp.changed")
                self.assertEqual(
                    ws.messages[-1]["payload"]["server_count"],
                    0,
                )
            finally:
                await server.close_async()
                server.close()


if __name__ == "__main__":
    unittest.main()
