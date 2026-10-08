from __future__ import annotations

import hashlib
import re
from typing import Iterable

from agent.mcp.client import (
    MCPClientError,
    MCPClientManager,
    MCPToolDescriptor,
)
from agent.tools.base import BaseTool, OutputCallback, ToolError, ToolResult


_TOOL_NAME_MAX = 64


def _safe_component(value: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9_-]+", "_", value.strip())
    safe = safe.strip("_")
    return safe or "unnamed"


def mcp_tool_name(server_name: str, tool_name: str) -> str:
    base = (
        "mcp__"
        + _safe_component(server_name)
        + "__"
        + _safe_component(tool_name)
    )
    if len(base) <= _TOOL_NAME_MAX:
        return base
    digest = hashlib.sha256(base.encode("utf-8")).hexdigest()[:10]
    return base[: _TOOL_NAME_MAX - 12] + "__" + digest


def _summary_from_result(payload: dict) -> str:
    result = payload.get("result")
    if not isinstance(result, dict):
        return "MCP tool completed."
    if result.get("truncated"):
        preview = str(result.get("preview") or "").strip()
        return (
            preview[:800]
            if preview
            else "MCP tool completed with truncated output."
        )
    value = result.get("value")
    if isinstance(value, dict):
        content = value.get("content")
        if isinstance(content, list):
            texts: list[str] = []
            for block in content:
                if isinstance(block, dict):
                    text = block.get("text")
                    if isinstance(text, str) and text.strip():
                        texts.append(text.strip())
            if texts:
                return "\n".join(texts)[:1000]
    return "MCP tool completed."


class MCPToolAdapter(BaseTool):
    def __init__(
        self,
        manager: MCPClientManager,
        descriptor: MCPToolDescriptor,
    ) -> None:
        self.manager = manager
        self.server_name = descriptor.server_name
        self.remote_name = descriptor.name
        self.name = mcp_tool_name(
            descriptor.server_name,
            descriptor.name,
        )
        self.description = (
            f"[MCP:{descriptor.server_name}] "
            + (
                descriptor.description
                or f"MCP tool {descriptor.name}"
            )
        )
        self.parameters = descriptor.input_schema

    async def execute(
        self,
        arguments: dict,
        *,
        on_output: OutputCallback | None = None,
    ) -> ToolResult:
        try:
            payload = await self.manager.call_tool(
                self.server_name,
                self.remote_name,
                arguments,
            )
        except MCPClientError as exc:
            raise ToolError(exc.code, exc.message) from exc

        is_error = bool(payload.get("is_error"))
        return ToolResult(
            ok=not is_error,
            summary=_summary_from_result(payload),
            data={
                "source": "mcp",
                "server": self.server_name,
                "remote_tool": self.remote_name,
                "payload": payload,
            },
        )


def mcp_tool_adapters(
    manager: MCPClientManager,
    descriptors: Iterable[MCPToolDescriptor],
) -> list[MCPToolAdapter]:
    adapters = [
        MCPToolAdapter(manager, descriptor)
        for descriptor in descriptors
    ]
    names = [tool.name for tool in adapters]
    if len(names) != len(set(names)):
        raise ToolError(
            "MCP_TOOL_NAME_COLLISION",
            "MCP tool names collide after namespace normalization.",
        )
    return sorted(adapters, key=lambda tool: tool.name)
