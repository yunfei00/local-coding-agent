from __future__ import annotations

import asyncio
import os
import time
from datetime import datetime, timezone
from typing import Any

from agent.core.diagnostics import redact_text
from agent.mcp.client import MCPClientError, MCPClientManager
from agent.mcp.settings import MCPSettingsManager, MCPStoredServer
from agent.server.projects import ProjectRegistry, ProjectSession
from agent.tools.mcp import MCPToolAdapter, mcp_tool_adapters


class MCPRuntime:
    def __init__(
        self,
        settings: MCPSettingsManager,
        projects: ProjectRegistry,
    ) -> None:
        self.settings = settings
        self.projects = projects
        self.client = MCPClientManager()
        self.secret_env: dict[str, dict[str, str]] = {}
        self.adapters: list[MCPToolAdapter] = []
        self.last_errors: dict[str, str] = {}
        self._refresh_lock = asyncio.Lock()
        self.call_history: list[dict[str, Any]] = []
        self._call_history_max = 200

    def set_secrets(
        self,
        payload: dict[str, Any],
    ) -> None:
        next_values: dict[str, dict[str, str]] = {}
        for server_id, raw in payload.items():
            if not isinstance(raw, dict):
                continue
            values: dict[str, str] = {}
            for key, value in raw.items():
                key_text = str(key).strip()
                if key_text:
                    values[key_text] = str(value)
            if values:
                next_values[str(server_id)] = values
        self.secret_env = next_values

    def record_call(self, entry: dict[str, Any]) -> None:
        safe = dict(entry)
        for k in ("arguments", "result", "error"):
            if k in safe:
                try:
                    safe[k] = redact_text(str(safe[k]), exact_secrets=self.exact_secrets(), max_chars=2000)
                except Exception:
                    safe[k] = "<unavailable>"
        self.call_history.append(safe)
        if len(self.call_history) > self._call_history_max:
            self.call_history = self.call_history[-self._call_history_max:]

    def get_call_history(self, server_id: str | None = None) -> list[dict[str, Any]]:
        items = list(self.call_history)
        if server_id:
            items = [i for i in items if i.get("server_id") == server_id]
        return items

    def _enabled(self) -> list[MCPStoredServer]:
        return [
            item
            for item in self.settings.list()
            if item.enabled
        ]

    def _clear_project_tools(self) -> None:
        for project in self.projects.list_projects():
            project.tools.unregister_prefix("mcp__")

    def apply_to_project(self, project: ProjectSession) -> None:
        project.tools.unregister_prefix("mcp__")
        for adapter in self.adapters:
            project.tools.register(adapter)

    async def _connect_server(
        self,
        item: MCPStoredServer,
    ) -> list[MCPToolAdapter]:
        try:
            await self.client.connect(item.name)
            descriptors = await self.client.list_tools(item.name)
            return mcp_tool_adapters(
                self.client,
                descriptors,
                trusted=item.trusted,
                server_permission=item.server_permission,
                tool_permissions=item.tool_permissions or {},
                call_recorder=self.record_call,
                server_id=item.id,
            )
        except MCPClientError as exc:
            self.last_errors[item.id] = exc.message
            return []
        except Exception as exc:
            self.last_errors[item.id] = str(exc)
            return []

    async def refresh(self) -> None:
        async with self._refresh_lock:
            try:
                await self.client.disconnect_all()
            except Exception:
                pass

            self._clear_project_tools()
            self.adapters = []
            self.last_errors = {}

            enabled = self._enabled()
            configs = [
                item.to_client_config(
                    secret_env=self.secret_env.get(item.id),
                )
                for item in enabled
            ]
            self.client = MCPClientManager(configs)

            if enabled:
                for item in enabled:
                    self.adapters.extend(
                        await self._connect_server(item)
                    )

            for project in self.projects.list_projects():
                self.apply_to_project(project)

    def _find(self, server_id: str) -> MCPStoredServer | None:
        for item in self.settings.list():
            if item.id == server_id:
                return item
        return None

    def _remove_server_adapters(self, server_name: str) -> None:
        self.adapters = [a for a in self.adapters if a.server_name != server_name]
        self._clear_project_tools()
        for project in self.projects.list_projects():
            self.apply_to_project(project)

    async def connect_server(self, server_id: str) -> None:
        item = self._find(server_id)
        if not item:
            raise ValueError(f"Unknown MCP server: {server_id}")
        if not item.enabled:
            raise ValueError("MCP server is disabled.")
        # ensure config exists
        try:
            self.client.status(item.name)
        except Exception:
            try:
                self.client.add_config(item.to_client_config(secret_env=self.secret_env.get(item.id)))
            except Exception:
                pass
        self._remove_server_adapters(item.name)
        self.adapters.extend(await self._connect_server(item))
        for project in self.projects.list_projects():
            self.apply_to_project(project)

    async def disconnect_server(self, server_id: str) -> None:
        item = self._find(server_id)
        if not item:
            raise ValueError(f"Unknown MCP server: {server_id}")
        try:
            await self.client.disconnect(item.name)
        except Exception:
            pass
        self._remove_server_adapters(item.name)

    async def reconnect_server(self, server_id: str) -> None:
        await self.disconnect_server(server_id)
        await self.connect_server(server_id)

    async def close(self) -> None:
        await self.client.disconnect_all()

    def _secret_configured(
        self,
        item: MCPStoredServer,
    ) -> bool:
        if not item.secret_env_keys:
            return True
        provided = self.secret_env.get(item.id, {})
        return all(
            key in provided or key in os.environ
            for key in item.secret_env_keys
        )

    def public_payload(self) -> dict[str, Any]:
        adapter_by_server: dict[str, list[MCPToolAdapter]] = {}
        for adapter in self.adapters:
            adapter_by_server.setdefault(
                adapter.server_name,
                [],
            ).append(adapter)

        servers: list[dict[str, Any]] = []
        for item in self.settings.list():
            try:
                status = self.client.status(item.name)
                status_payload = status.to_dict()
            except MCPClientError:
                status_payload = {
                    "name": item.name,
                    "transport": item.transport,
                    "connected": False,
                    "error": self.last_errors.get(item.id),
                }

            tools = []
            for adapter in sorted(
                adapter_by_server.get(item.name, []),
                key=lambda tool: tool.name,
            ):
                metadata = adapter.permission_metadata()
                tools.append(
                    {
                        "name": adapter.name,
                        "remote_tool": adapter.remote_name,
                        "read_only": bool(metadata.get("read_only")),
                        "risk": metadata.get("risk"),
                        "permission": metadata.get("permission_override") or item.server_permission or "ask",
                    }
                )

            public = item.to_public_dict()
            public["secret_configured"] = self._secret_configured(item)
            public["status"] = status_payload
            public["tools"] = tools
            servers.append(public)

        return {
            "servers": servers,
            "server_count": len(servers),
            "enabled_count": sum(
                1 for item in servers if item.get("enabled")
            ),
            "connected_count": sum(
                1
                for item in servers
                if (
                    isinstance(item.get("status"), dict)
                    and item["status"].get("connected")
                )
            ),
            "tool_count": sum(
                len(item.get("tools") or [])
                for item in servers
            ),
            "call_history": list(self.call_history[-100:]),
        }

    def diagnostic_payload(self) -> dict[str, Any]:
        public = self.public_payload()
        return {
            "server_count": public["server_count"],
            "enabled_count": public["enabled_count"],
            "connected_count": public["connected_count"],
            "tool_count": public["tool_count"],
            "servers": [
                {
                    "name": item["name"],
                    "transport": item["transport"],
                    "enabled": item["enabled"],
                    "trusted": item["trusted"],
                    "secret_configured": item["secret_configured"],
                    "connected": bool(
                        (item.get("status") or {}).get("connected")
                    ),
                    "protocol_version": (
                        item.get("status") or {}
                    ).get("protocol_version"),
                    "tool_count": len(item.get("tools") or []),
                    "error": redact_text(
                        str(
                            (item.get("status") or {}).get("error")
                            or ""
                        ),
                        exact_secrets=self.exact_secrets(),
                        max_chars=300,
                    ) or None,
                }
                for item in public["servers"]
            ],
        }

    def exact_secrets(self) -> tuple[str, ...]:
        return tuple(
            value
            for server in self.secret_env.values()
            for value in server.values()
            if value
        )
