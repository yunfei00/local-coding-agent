"""MCP sessions outlive requests and can be disconnected from other tasks."""
import asyncio
from pathlib import Path
import sys
import unittest

from agent.mcp.client import MCPClientManager, MCPServerConfig


class MCPLifetimeTests(unittest.IsolatedAsyncioTestCase):
    async def test_two_servers_survive_cross_task_requests_and_fifo_disconnect(self):
        fixture = Path(__file__).parent / "fixtures/mcp_test_server.py"
        manager = MCPClientManager([MCPServerConfig(name=name, transport="stdio",
            command=sys.executable, args=(str(fixture.resolve()),), timeout_seconds=15)
            for name in ("first", "second")])
        try:
            await asyncio.gather(*(manager.connect(name) for name in ("first", "second")))
            self.assertTrue(manager.status("first").connected)
            self.assertTrue(manager.status("second").connected)
            await asyncio.create_task(manager.disconnect("first"))
            self.assertFalse(manager.status("first").connected)
            result = await asyncio.create_task(manager.call_tool("second", "echo", {"message": "still connected"}))
            self.assertFalse(result["is_error"])
            self.assertTrue(manager.status("second").connected)
            await asyncio.create_task(manager.disconnect_all())
            self.assertFalse(manager.status("second").connected)
            self.assertFalse([task for task in asyncio.all_tasks() if task.get_name().startswith("mcp:")])
        finally:
            await manager.disconnect_all()
