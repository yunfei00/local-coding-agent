from __future__ import annotations

import asyncio
import os
import socket
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from agent.mcp.client import (
    MCPClientError,
    MCPClientManager,
    MCPServerConfig,
)
from agent.tools.mcp import mcp_tool_adapters, mcp_tool_name
from agent.tools.registry import ToolRegistry
from agent.tools.workspace import Workspace


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "mcp_test_server.py"
FAILING_FIXTURE = (
    ROOT / "tests" / "fixtures" / "mcp_failing_server.py"
)


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


async def wait_for_port(
    process: subprocess.Popen,
    port: int,
    *,
    timeout: float = 10.0,
) -> None:
    deadline = asyncio.get_running_loop().time() + timeout
    while asyncio.get_running_loop().time() < deadline:
        if process.poll() is not None:
            stderr = (
                process.stderr.read()
                if process.stderr is not None
                else ""
            )
            raise RuntimeError(
                f"HTTP MCP fixture exited early: {stderr}"
            )
        try:
            reader, writer = await asyncio.open_connection(
                "127.0.0.1",
                port,
            )
            writer.close()
            await writer.wait_closed()
            return
        except OSError:
            await asyncio.sleep(0.05)
    raise TimeoutError("HTTP MCP fixture did not open its port.")


class MCPConfigTests(unittest.TestCase):
    def test_rejects_invalid_transport_configuration(self) -> None:
        with self.assertRaises(ValueError):
            MCPServerConfig(
                name="bad",
                transport="stdio",
            ).validate()

        with self.assertRaises(ValueError):
            MCPServerConfig(
                name="bad",
                transport="streamable_http",
                url="file:///tmp/server",
            ).validate()

    def test_namespaced_tool_name_is_deterministic_and_bounded(self) -> None:
        value = mcp_tool_name(
            "my server",
            "tool with spaces",
        )
        self.assertEqual(value, "mcp__my_server__tool_with_spaces")

        long_value = mcp_tool_name("s" * 100, "t" * 100)
        self.assertLessEqual(len(long_value), 64)
        self.assertEqual(
            long_value,
            mcp_tool_name("s" * 100, "t" * 100),
        )


class MCPClientManagerTests(unittest.IsolatedAsyncioTestCase):
    async def test_python_alias_resolves_to_agent_virtualenv(self) -> None:
        virtual_env = str(Path(sys.executable).resolve().parent.parent)
        manager = MCPClientManager(
            [
                MCPServerConfig(
                    name="python-alias",
                    transport="stdio",
                    command="python",
                    args=("tests/fixtures/mcp_test_server.py",),
                    timeout_seconds=15,
                )
            ]
        )
        try:
            with patch.dict(
                os.environ,
                {"VIRTUAL_ENV": virtual_env},
                clear=False,
            ):
                status = await manager.connect("python-alias")
                self.assertTrue(status.connected)
                self.assertEqual(
                    Path(status.effective_command or "").resolve(),
                    Path(sys.executable).resolve(),
                )
                tools = await manager.list_tools("python-alias")
                self.assertEqual(
                    [item.name for item in tools],
                    ["echo", "large_text"],
                )
        finally:
            await manager.disconnect_all()

    async def test_stdio_discovery_resource_call_reconnect_and_registry(self) -> None:
        manager = MCPClientManager(
            [
                MCPServerConfig(
                    name="stdio-test",
                    transport="stdio",
                    command=sys.executable,
                    args=(str(FIXTURE),),
                    timeout_seconds=15,
                )
            ]
        )
        try:
            status = await manager.connect("stdio-test")
            self.assertTrue(status.connected)
            self.assertTrue(status.protocol_version)

            descriptors = await manager.list_tools("stdio-test")
            self.assertEqual(
                [item.name for item in descriptors],
                ["echo", "large_text"],
            )

            resources = await manager.list_resources("stdio-test")
            self.assertEqual(
                [item.uri for item in resources],
                ["test://local/greeting"],
            )

            resource = await manager.read_resource(
                "stdio-test",
                "test://local/greeting",
            )
            self.assertFalse(resource["result"]["truncated"])
            self.assertIn(
                "hello from mcp resource",
                str(resource["result"]["value"]),
            )

            echo = await manager.call_tool(
                "stdio-test",
                "echo",
                {"message": "hello"},
            )
            self.assertFalse(echo["is_error"])
            self.assertIn("hello", str(echo["result"]))

            adapters = mcp_tool_adapters(manager, descriptors)
            with tempfile.TemporaryDirectory() as root:
                registry = ToolRegistry(
                    Workspace(root),
                    extra_tools=adapters,
                )
                names = registry.names
                self.assertIn(
                    "mcp__stdio-test__echo",
                    names,
                )
                schema_names = [
                    item["function"]["name"]
                    for item in registry.schemas()
                ]
                self.assertIn(
                    "mcp__stdio-test__echo",
                    schema_names,
                )
                result = await registry.execute(
                    "mcp__stdio-test__echo",
                    {"message": "from registry"},
                )
                self.assertTrue(result.ok)
                self.assertEqual(
                    result.data["source"],
                    "mcp",
                )
                self.assertIn(
                    "from registry",
                    result.summary,
                )

            reconnected = await manager.reconnect("stdio-test")
            self.assertTrue(reconnected.connected)
            second = await manager.call_tool(
                "stdio-test",
                "echo",
                {"message": "after reconnect"},
            )
            self.assertFalse(second["is_error"])
        finally:
            await manager.disconnect_all()

    async def test_output_is_bounded(self) -> None:
        manager = MCPClientManager(
            [
                MCPServerConfig(
                    name="bounded",
                    transport="stdio",
                    command=sys.executable,
                    args=(str(FIXTURE),),
                    timeout_seconds=15,
                )
            ],
            max_output_chars=2048,
        )
        try:
            await manager.connect("bounded")
            result = await manager.call_tool(
                "bounded",
                "large_text",
                {"size": 20000},
            )
            self.assertTrue(result["result"]["truncated"])
            self.assertEqual(
                len(result["result"]["preview"]),
                2048,
            )
        finally:
            await manager.disconnect_all()

    async def test_one_server_failure_does_not_break_another(self) -> None:
        manager = MCPClientManager(
            [
                MCPServerConfig(
                    name="good",
                    transport="stdio",
                    command=sys.executable,
                    args=(str(FIXTURE),),
                    timeout_seconds=15,
                ),
                MCPServerConfig(
                    name="bad",
                    transport="stdio",
                    command="lca-command-that-does-not-exist",
                    timeout_seconds=2,
                ),
            ]
        )
        try:
            await manager.connect("good")
            with self.assertRaises(MCPClientError) as ctx:
                await manager.connect("bad")
            self.assertEqual(
                ctx.exception.code,
                "MCP_CONNECT_FAILED",
            )
            self.assertFalse(manager.status("bad").connected)

            result = await manager.call_tool(
                "good",
                "echo",
                {"message": "still alive"},
            )
            self.assertFalse(result["is_error"])
            self.assertTrue(manager.status("good").connected)
        finally:
            await manager.disconnect_all()

    async def test_stdio_failure_surfaces_server_stderr(self) -> None:
        manager = MCPClientManager(
            [
                MCPServerConfig(
                    name="failing",
                    transport="stdio",
                    command=sys.executable,
                    args=(str(FAILING_FIXTURE),),
                    timeout_seconds=5,
                )
            ]
        )
        try:
            with self.assertRaises(MCPClientError) as ctx:
                await manager.connect("failing")
            self.assertEqual(ctx.exception.code, "MCP_CONNECT_FAILED")
            self.assertIn(
                "PHASE23_STDIO_FIXTURE_FAILURE",
                ctx.exception.message,
            )
            status = manager.status("failing")
            self.assertFalse(status.connected)
            self.assertIn(
                "PHASE23_STDIO_FIXTURE_FAILURE",
                status.error or "",
            )
        finally:
            await manager.disconnect_all()

    async def test_missing_python_script_reports_resolved_path(self) -> None:
        manager = MCPClientManager(
            [
                MCPServerConfig(
                    name="missing-script",
                    transport="stdio",
                    command=sys.executable,
                    args=("tests/fixtures/does_not_exist.py",),
                    timeout_seconds=5,
                )
            ]
        )
        try:
            with self.assertRaises(MCPClientError) as ctx:
                await manager.connect("missing-script")
            self.assertIn(
                "MCP Python script does not exist",
                ctx.exception.message,
            )
            status = manager.status("missing-script")
            self.assertFalse(status.connected)
            self.assertIn(
                "does_not_exist.py",
                status.error or "",
            )
        finally:
            await manager.disconnect_all()

    async def test_streamable_http_transport(self) -> None:
        port = free_port()
        process = subprocess.Popen(
            [
                sys.executable,
                str(FIXTURE),
                "--http",
                "--port",
                str(port),
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        manager = MCPClientManager(
            [
                MCPServerConfig(
                    name="http-test",
                    transport="streamable_http",
                    url=f"http://127.0.0.1:{port}/mcp",
                    timeout_seconds=15,
                )
            ]
        )
        try:
            await wait_for_port(process, port)
            status = await manager.connect("http-test")
            self.assertTrue(status.connected)

            tools = await manager.list_tools("http-test")
            self.assertEqual(
                [item.name for item in tools],
                ["echo", "large_text"],
            )
            result = await manager.call_tool(
                "http-test",
                "echo",
                {"message": "over http"},
            )
            self.assertFalse(result["is_error"])

            resources = await manager.list_resources("http-test")
            self.assertEqual(
                resources[0].uri,
                "test://local/greeting",
            )
        finally:
            await manager.disconnect_all()
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)


if __name__ == "__main__":
    unittest.main()
