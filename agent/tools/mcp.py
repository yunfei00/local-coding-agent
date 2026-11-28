from __future__ import annotations

import asyncio
import hashlib
import re
import time
from datetime import datetime, timezone
from typing import Iterable

from agent.mcp.client import (
    MCPClientError,
    MCPClientManager,
    MCPToolDescriptor,
)
from agent.tools.base import BaseTool, OutputCallback, ToolError, ToolResult


_TOOL_NAME_MAX = 64
_MUTATING_NAME = re.compile(
    r"(?i)(?:^|[_-])(?:write|create|update|edit|delete|remove|move|rename|"
    r"execute|run|shell|command|commit|push|publish|deploy|send|post|put|patch)"
)
_GIT_COMMIT_NAME = re.compile(r"(?i)(?:^|[_-])commit(?:$|[_-])")
_GIT_PUBLISH_NAME = re.compile(
    r"(?i)(?:^|[_-])(?:push|publish)(?:$|[_-])"
)


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
        *,
        trusted: bool = False,
        permission_override: str | None = None,
        call_recorder=None,
        server_id: str | None = None,
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
        self.trusted = trusted
        self.permission_override = permission_override if permission_override in {"allow","ask","deny"} else None
        self.call_recorder = call_recorder
        self.server_id = server_id
        self.read_only = bool(
            trusted
            and descriptor.read_only_hint
            and not descriptor.destructive_hint
            and not _MUTATING_NAME.search(descriptor.name)
        )

    def permission_metadata(self) -> dict:
        risk = "mcp_read_only" if self.read_only else "mcp_mutating"
        if _GIT_COMMIT_NAME.search(self.remote_name):
            risk = "git_commit"
        elif _GIT_PUBLISH_NAME.search(self.remote_name):
            risk = "git_publish"
        return {
            "source": "mcp",
            "server": self.server_name,
            "remote_tool": self.remote_name,
            "trusted": self.trusted,
            "read_only": self.read_only,
            "risk": risk,
            "permission_override": self.permission_override,
        }

    async def execute(
        self,
        arguments: dict,
        *,
        on_output: OutputCallback | None = None,
    ) -> ToolResult:
        started = time.time()
        started_at = datetime.now(timezone.utc).isoformat()
        record = {
            "server": self.server_name,
            "server_id": self.server_id,
            "tool": self.remote_name,
            "arguments": arguments,
            "started_at": started_at,
            "status": "running",
        }
        try:
            payload = await self.manager.call_tool(
                self.server_name,
                self.remote_name,
                arguments,
            )
        except asyncio.CancelledError:
            record.update({
                "status": "cancelled",
                "cancelled_at": datetime.now(timezone.utc).isoformat(),
                "duration_ms": int((time.time()-started)*1000),
                "cancel_note": "Client-side cancellation requested. Server may not support cancellation; any side effects already performed are not rolled back.",
            })
            if self.call_recorder:
                try: self.call_recorder(record)
                except Exception: pass
            raise
        except MCPClientError as exc:
            record.update({"status": "failed", "ended_at": datetime.now(timezone.utc).isoformat(), "duration_ms": int((time.time()-started)*1000), "error": exc.message})
            if self.call_recorder:
                try: self.call_recorder(record)
                except Exception: pass
            raise ToolError(exc.code, exc.message) from exc

        is_error = bool(payload.get("is_error"))
        record.update({"status": "failed" if is_error else "completed", "ended_at": datetime.now(timezone.utc).isoformat(), "duration_ms": int((time.time()-started)*1000), "result": payload})
        if self.call_recorder:
            try: self.call_recorder(record)
            except Exception: pass
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
    *,
    trusted: bool = False,
    server_permission: str = "ask",
    tool_permissions: dict[str, str] | None = None,
    call_recorder=None,
    server_id: str | None = None,
) -> list[MCPToolAdapter]:
    tool_permissions = tool_permissions or {}
    adapters = []
    for descriptor in descriptors:
        override = tool_permissions.get(descriptor.name) or server_permission
        adapters.append(MCPToolAdapter(manager, descriptor, trusted=trusted, permission_override=override, call_recorder=call_recorder, server_id=server_id))
    names = [tool.name for tool in adapters]
    if len(names) != len(set(names)):
        raise ToolError(
            "MCP_TOOL_NAME_COLLISION",
            "MCP tool names collide after namespace normalization.",
        )
    return sorted(adapters, key=lambda tool: tool.name)
