from __future__ import annotations

import argparse
import asyncio
import json
import os
import platform
import secrets
import sys
from collections import deque
from contextlib import suppress
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from aiohttp import WSMsgType, web

from agent.core.agent_loop import (
    ToolLoopGuard,
    canonical_tool_fingerprint,
    compact_tool_payload,
)
from agent.core.context import ContextBudgetManager
from agent.core.explicit_context import (
    context_blocks_for_files,
    extract_file_mentions,
    load_context_file,
    normalize_context_path,
)
from agent.core.diagnostics import (
    database_summary,
    prompt_rules_summary,
    redact_path,
    redact_text,
    sanitize_provider_status,
)
from agent.core.settings import RuntimeSettings
from agent.core.version import APP_VERSION, PROTOCOL_VERSION
from agent.llm.base import ProviderError, ToolCall
from agent.mcp.runtime import MCPRuntime
from agent.mcp.settings import MCPSettingsManager
from agent.permissions.approval import (
    APPROVAL_DENY,
    ApprovalManager,
)
from agent.persistence.store import SQLiteStore
from agent.permissions.policy import PermissionMode, PermissionPolicy
from agent.core.prompt_rules import PromptRuleManager
from agent.server.projects import ProjectRegistry
from agent.server.protocol import envelope, new_id, validate_client_message
from agent.tools.base import ToolError


SYSTEM_PROMPT = """You are Local Coding Agent, a local software-development agent.

When a workspace is open, the runtime exposes only the tools permitted by the current permission mode.
Treat the runtime permission decision as authoritative.
Work deliberately:
- inspect the project before editing;
- do not invent file contents or command results;
- prefer small precise edits;
- use apply_patch for small edits and write_file for new/full-file content;
- run relevant tests or build commands after changes;
- inspect git_status/git_diff before declaring completion;
- preserve the user's existing uncommitted work; never overwrite unrelated dirty changes;
- if a target file is already modified, inspect the relevant diff before editing and make the smallest compatible change;
- if a command fails, analyze its real output before deciding the next step;
- never claim a test passed unless the tool result actually shows success;
- never create a Git commit or push/publish changes unless the user's current request explicitly asks for that action; approval does not substitute for explicit intent.

The permission policy is enforced by the runtime. Never try to bypass it.
When an operation requires approval, wait for the user's decision and continue based on the structured result.

You are responsible for completing the task, not just suggesting steps:
- after a real command failure, inspect the actual output and change approach when appropriate;
- do not repeatedly call the same tool with the same arguments without new information;
- after modifying code, run a relevant existing validation command when it is safe and identifiable;
- after any file modification, inspect the Git diff after the latest change;
- if validation cannot be performed, state that clearly instead of claiming success.

Keep user-facing explanations concise and focus on completing the requested development task."""


def build_health_payload(port: int) -> dict[str, Any]:
    return {
        "ok": True,
        "service": "local-coding-agent",
        "version": APP_VERSION,
        "protocol": PROTOCOL_VERSION,
        "port": port,
    }


def _bounded_env_int(
    name: str,
    default: int,
    *,
    minimum: int,
    maximum: int,
) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return min(max(value, minimum), maximum)


class AgentServer:
    MAX_MODEL_STEPS = 16
    MAX_TOOL_CALLS = 40
    MAX_BLOCKED_REPEATS = 3
    MAX_CONSECUTIVE_TOOL_FAILURES = 4
    MODEL_RETRY_ATTEMPTS = 2

    def __init__(self, token: str) -> None:
        self.token = token
        self.store = SQLiteStore()
        self.projects = ProjectRegistry(self.store)
        self.mcp_settings = MCPSettingsManager(self.store)
        self.mcp_runtime = MCPRuntime(self.mcp_settings, self.projects)
        self.prompt_rules = PromptRuleManager(self.store)
        self.settings = RuntimeSettings.load(self.store)
        self.openai_api_key: str | None = os.getenv("LCA_OPENAI_API_KEY")
        self.provider = self.settings.create_provider(
            openai_api_key=self.openai_api_key,
        )
        self.max_model_steps = self.settings.max_model_steps
        self.max_tool_calls = self.settings.max_tool_calls
        self.max_blocked_repeats = self.settings.max_blocked_repeats
        self.max_consecutive_tool_failures = (
            self.settings.max_consecutive_tool_failures
        )
        self.model_retry_attempts = self.settings.model_retry_attempts
        self.context_reserved_output_tokens = (
            self.settings.context_reserved_output_tokens
        )
        self.active_turns: dict[str, asyncio.Task[None]] = {}
        self.available_models: set[str] = set()
        self.default_model: str | None = self.provider.preferred_model
        self.permissions = PermissionPolicy(PermissionMode.WORKSPACE)
        saved_permission = self.store.get_setting("permission_mode")
        if saved_permission:
            try:
                self.permissions.set_mode(saved_permission)
            except ValueError:
                pass
        self.approvals = ApprovalManager()
        self.recent_errors: deque[dict[str, Any]] = deque(maxlen=20)
        self.last_context_usage: dict[str, Any] | None = None
        self._sync_workspace_permissions()

    def authorized(self, request: web.Request) -> bool:
        return request.headers.get("Authorization") == f"Bearer {self.token}"

    async def health(self, request: web.Request) -> web.Response:
        if not self.authorized(request):
            return web.json_response({"ok": False, "error": "unauthorized"}, status=401)
        transport = request.transport
        if transport is None:
            return web.json_response({"ok": False, "error": "transport_missing"}, status=500)
        port = int(transport.get_extra_info("sockname")[1])
        return web.json_response(build_health_payload(port))

    async def shutdown(self, request: web.Request) -> web.Response:
        if not self.authorized(request):
            return web.json_response({"ok": False, "error": "unauthorized"}, status=401)
        response = web.json_response({"ok": True})
        asyncio.get_running_loop().call_later(0.1, request.app["stop_event"].set)
        return response

    async def websocket(self, request: web.Request) -> web.StreamResponse:
        if not self.authorized(request):
            return web.json_response({"ok": False, "error": "unauthorized"}, status=401)

        ws = web.WebSocketResponse(heartbeat=20)
        await ws.prepare(request)
        await ws.send_json(
            envelope(
                "server.ready",
                self._server_ready_payload(),
            )
        )

        owned_turns: set[str] = set()
        try:
            async for msg in ws:
                if msg.type == WSMsgType.TEXT:
                    try:
                        data = json.loads(msg.data)
                    except json.JSONDecodeError:
                        await ws.send_json(
                            envelope(
                                "error",
                                {
                                    "code": "INVALID_JSON",
                                    "message": "Message is not valid JSON.",
                                    "recoverable": True,
                                },
                            )
                        )
                        continue

                    valid, reason = validate_client_message(data)
                    if not valid:
                        await ws.send_json(
                            envelope(
                                "error",
                                {
                                    "code": "INVALID_MESSAGE",
                                    "message": reason,
                                    "recoverable": True,
                                },
                                request_id=data.get("request_id") if isinstance(data, dict) else None,
                            )
                        )
                        continue

                    await self.handle_message(ws, data, owned_turns)
                elif msg.type == WSMsgType.ERROR:
                    break
        finally:
            for turn_id in list(owned_turns):
                task = self.active_turns.get(turn_id)
                if task and not task.done():
                    task.cancel()
            with suppress(Exception):
                await self.mcp_runtime.close()

        return ws

    def _server_ready_payload(self) -> dict[str, Any]:
        return {
            "version": APP_VERSION,
            "protocol": PROTOCOL_VERSION,
            "provider": self.provider.provider_name,
            "preferred_model": self.provider.preferred_model,
            "context_window": self.provider.context_window,
            "settings": self._settings_payload(),
            "permission": {
                "mode": self.permissions.mode.value,
                "available_modes": self.permissions.available_modes,
            },
            "persistence": {
                "database": str(self.store.path),
            },
            "projects": self.projects.list_payload(),
            "active_project": (
                self.projects.project_payload(self.projects.active)
                if self.projects.active
                else None
            ),
        }

    async def handle_message(
        self,
        ws: web.WebSocketResponse,
        data: dict[str, Any],
        owned_turns: set[str],
    ) -> None:
        message_type = data["type"]
        payload = data.get("payload") or {}
        request_id = data.get("request_id")

        if message_type == "client.hello":
            await ws.send_json(
                envelope("server.ready", self._server_ready_payload(), request_id=request_id)
            )
            return

        if message_type == "diagnostics.get":
            await ws.send_json(
                envelope(
                    "diagnostics.loaded",
                    await self._diagnostics_payload(),
                    request_id=request_id,
                )
            )
            return

        if message_type in {
            "context.get",
            "context.pin",
            "context.unpin",
            "context.refresh",
        }:
            project = self.projects.active
            if not project:
                await self.send_error(
                    ws,
                    "WORKSPACE_REQUIRED",
                    "Open a workspace before managing context.",
                    request_id=request_id,
                    thread_id=data.get("thread_id"),
                )
                return

            thread_id = str(
                payload.get("thread_id")
                or data.get("thread_id")
                or project.active_thread_id
                or ""
            ).strip()
            if not thread_id or not project.state.get_thread(thread_id):
                await self.send_error(
                    ws,
                    "THREAD_NOT_FOUND",
                    "A valid thread is required for pinned context.",
                    request_id=request_id,
                    thread_id=thread_id or None,
                )
                return

            if message_type != "context.get" and any(
                not task.done() for task in self.active_turns.values()
            ):
                await self.send_error(
                    ws,
                    "TURN_RUNNING",
                    "Stop the active turn before changing pinned or repository context.",
                    request_id=request_id,
                    thread_id=thread_id,
                )
                return

            try:
                if message_type == "context.pin":
                    relative = normalize_context_path(
                        project.workspace,
                        str(payload.get("path") or ""),
                    )
                    loaded = load_context_file(
                        project.workspace,
                        relative,
                        source="pinned_file",
                    )
                    if loaded.status != "ready":
                        raise ValueError(
                            f"Cannot pin {relative}: {loaded.status}."
                        )
                    self.store.pin_context(
                        thread_id=thread_id,
                        path=relative,
                        created_at=datetime.now(timezone.utc).isoformat(),
                    )
                elif message_type == "context.unpin":
                    relative = normalize_context_path(
                        project.workspace,
                        str(payload.get("path") or ""),
                    )
                    self.store.unpin_context(
                        thread_id=thread_id,
                        path=relative,
                    )
                elif message_type == "context.refresh":
                    project.ensure_repository_map().build()

                pinned = [
                    load_context_file(
                        project.workspace,
                        str(row["path"]),
                        source="pinned_file",
                    ).to_dict()
                    for row in self.store.list_pinned_context(thread_id)
                ]
                repo_map = project.ensure_repository_map()
                result_payload = {
                    "thread_id": thread_id,
                    "repository_map": {
                        **repo_map.payload(),
                        "files": repo_map.file_paths(limit=500),
                    },
                    "pinned": pinned,
                }
            except ValueError as exc:
                await self.send_error(
                    ws,
                    "CONTEXT_INVALID",
                    str(exc),
                    request_id=request_id,
                    thread_id=thread_id,
                )
                return

            await ws.send_json(
                envelope(
                    (
                        "context.loaded"
                        if message_type == "context.get"
                        else "context.changed"
                    ),
                    result_payload,
                    request_id=request_id,
                    thread_id=thread_id,
                )
            )
            return

        if message_type == "git.overview":
            project = self.projects.active
            if not project:
                await self.send_error(
                    ws,
                    "WORKSPACE_REQUIRED",
                    "Open a workspace before reading Git state.",
                    request_id=request_id,
                )
                return

            results: dict[str, Any] = {}
            errors: list[dict[str, str]] = []
            for tool_name, key in (
                ("git_status", "status"),
                ("git_branches", "branches"),
                ("git_worktree_list", "worktrees"),
            ):
                try:
                    result = await project.tools.execute(tool_name, {})
                    results[key] = result.data
                    if not result.ok:
                        errors.append(
                            {
                                "tool": tool_name,
                                "message": (
                                    result.stderr.strip()
                                    or result.summary
                                ),
                            }
                        )
                except ToolError as exc:
                    results[key] = {}
                    errors.append(
                        {
                            "tool": tool_name,
                            "message": exc.message,
                        }
                    )

            await ws.send_json(
                envelope(
                    "git.loaded",
                    {
                        "project_id": project.id,
                        "project_path": str(project.workspace.root),
                        **results,
                        "errors": errors,
                    },
                    request_id=request_id,
                )
            )
            return

        if message_type == "git.worktree.open":
            if any(not task.done() for task in self.active_turns.values()):
                await self.send_error(
                    ws,
                    "TURN_RUNNING",
                    "Stop the active turn before switching worktrees.",
                    request_id=request_id,
                )
                return

            source = self.projects.active
            if not source:
                await self.send_error(
                    ws,
                    "WORKSPACE_REQUIRED",
                    "Open a Git workspace before opening a managed worktree.",
                    request_id=request_id,
                )
                return

            requested_path = str(payload.get("path") or "").strip()
            requested_model = str(payload.get("model") or "").strip() or None
            if not requested_path:
                await self.send_error(
                    ws,
                    "WORKTREE_PATH_REQUIRED",
                    "Worktree path is required.",
                    request_id=request_id,
                )
                return

            try:
                listed = await source.tools.execute("git_worktree_list", {})
                records = listed.data.get("worktrees") or []
                target = Path(requested_path).expanduser().resolve(strict=False)
                allowed = next(
                    (
                        item
                        for item in records
                        if bool(item.get("managed"))
                        and Path(
                            str(item.get("path") or "")
                        ).resolve(strict=False)
                        == target
                    ),
                    None,
                )
                if allowed is None:
                    raise ToolError(
                        "WORKTREE_NOT_MANAGED",
                        "Only a managed worktree of the active Git repository can be opened here.",
                    )

                project, thread, created = self.projects.open(
                    target,
                    active_model=(
                        requested_model
                        or self.default_model
                        or self.provider.preferred_model
                    ),
                )
            except (ToolError, OSError) as exc:
                message = exc.message if isinstance(exc, ToolError) else str(exc)
                await self.send_error(
                    ws,
                    "WORKTREE_OPEN_FAILED",
                    message,
                    request_id=request_id,
                )
                return

            project.workspace.set_full_access(
                self.permissions.mode == PermissionMode.FULL_ACCESS
            )
            self.mcp_runtime.apply_to_project(project)
            response_payload = self.projects.project_payload(project)
            response_payload["created"] = created
            response_payload["worktree"] = {
                "managed": True,
                "branch": allowed.get("branch") if allowed else None,
                "source_project_id": source.id,
                "source_project_path": str(source.workspace.root),
            }
            await ws.send_json(
                envelope(
                    "project.opened",
                    response_payload,
                    request_id=request_id,
                    thread_id=thread.id,
                )
            )
            return

        if message_type == "permission.get":
            await ws.send_json(
                envelope(
                    "permission.loaded",
                    {
                        "mode": self.permissions.mode.value,
                        "available_modes": self.permissions.available_modes,
                    },
                    request_id=request_id,
                )
            )
            return

        if message_type == "permission.set":
            if any(not task.done() for task in self.active_turns.values()):
                await self.send_error(
                    ws,
                    "TURN_RUNNING",
                    "Stop the active turn before changing permission mode.",
                    request_id=request_id,
                )
                return
            requested = str(payload.get("mode") or "")
            try:
                mode = self.permissions.set_mode(requested)
            except ValueError as exc:
                await self.send_error(
                    ws,
                    "INVALID_PERMISSION_MODE",
                    str(exc),
                    request_id=request_id,
                )
                return

            self._sync_workspace_permissions()
            self.store.set_setting("permission_mode", mode.value)
            await ws.send_json(
                envelope(
                    "permission.changed",
                    {
                        "mode": mode.value,
                        "available_modes": self.permissions.available_modes,
                    },
                    request_id=request_id,
                )
            )
            return

        if message_type == "settings.get":
            await ws.send_json(
                envelope(
                    "settings.loaded",
                    self._settings_payload(),
                    request_id=request_id,
                )
            )
            return

        if message_type in {"settings.apply", "settings.reset"}:
            if any(not task.done() for task in self.active_turns.values()):
                await self.send_error(
                    ws,
                    "TURN_RUNNING",
                    "Stop the active turn before changing runtime settings.",
                    request_id=request_id,
                )
                return

            try:
                if message_type == "settings.reset":
                    next_settings = RuntimeSettings.defaults()
                else:
                    raw_settings = payload.get("settings")
                    if not isinstance(raw_settings, dict):
                        raise ValueError("settings must be an object.")
                    next_settings = RuntimeSettings.validate(
                        {
                            **asdict(self.settings),
                            **raw_settings,
                        }
                    )
            except ValueError as exc:
                await self.send_error(
                    ws,
                    "INVALID_SETTINGS",
                    str(exc),
                    request_id=request_id,
                )
                return

            next_settings.save(self.store)
            self._apply_runtime_settings(next_settings)
            status = await self.provider.get_status()
            await ws.send_json(
                envelope(
                    "settings.changed",
                    {
                        **self._settings_payload(),
                        "provider_status": status,
                    },
                    request_id=request_id,
                )
            )
            return

        if message_type == "settings.secret":
            if any(not task.done() for task in self.active_turns.values()):
                await self.send_error(
                    ws,
                    "TURN_RUNNING",
                    "Stop the active turn before changing provider credentials.",
                    request_id=request_id,
                )
                return
            api_key = payload.get("openai_api_key")
            if not isinstance(api_key, str):
                await self.send_error(
                    ws,
                    "INVALID_SETTINGS_SECRET",
                    "openai_api_key must be a string.",
                    request_id=request_id,
                )
                return
            self.openai_api_key = api_key
            if self.settings.provider == "openai_compatible":
                self.provider = self.settings.create_provider(
                    openai_api_key=self.openai_api_key,
                )
                self.available_models.clear()
                self.default_model = self.provider.preferred_model or None
            await ws.send_json(
                envelope(
                    "settings.secret.changed",
                    {
                        "api_key_configured": bool(api_key),
                    },
                    request_id=request_id,
                )
            )
            return

        if message_type == "prompt_rules.get":
            scope = str(payload.get("scope") or "").strip().lower()
            if not scope:
                project = self.projects.active
                thread_id = str(
                    payload.get("thread_id")
                    or data.get("thread_id")
                    or (project.active_thread_id if project else "")
                    or ""
                ).strip() or None
                await ws.send_json(
                    envelope(
                        "prompt_rules.loaded",
                        {
                            "project_id": project.id if project else None,
                            "thread_id": thread_id,
                            **self.prompt_rules.hierarchy_payload(
                                project_id=project.id if project else None,
                                thread_id=thread_id,
                            ),
                        },
                        request_id=request_id,
                        thread_id=thread_id,
                    )
                )
                return

            try:
                scope_id = self._resolve_prompt_rule_scope_id(
                    scope,
                    payload,
                    data,
                )
                rule = self.prompt_rules.get(scope, scope_id)
            except ValueError as exc:
                await self.send_error(
                    ws,
                    "PROMPT_RULE_INVALID",
                    str(exc),
                    request_id=request_id,
                    thread_id=data.get("thread_id"),
                )
                return

            await ws.send_json(
                envelope(
                    "prompt_rules.loaded",
                    {
                        "scope": scope,
                        "scope_id": scope_id,
                        "rule": rule.to_dict() if rule else None,
                    },
                    request_id=request_id,
                    thread_id=(scope_id if scope == "thread" else data.get("thread_id")),
                )
            )
            return

        if message_type in {
            "prompt_rules.set",
            "prompt_rules.toggle",
            "prompt_rules.reset",
        }:
            if any(not task.done() for task in self.active_turns.values()):
                await self.send_error(
                    ws,
                    "TURN_RUNNING",
                    "Stop the active turn before changing Prompt Rules.",
                    request_id=request_id,
                    thread_id=data.get("thread_id"),
                )
                return

            scope = str(payload.get("scope") or "").strip().lower()
            try:
                scope_id = self._resolve_prompt_rule_scope_id(
                    scope,
                    payload,
                    data,
                )
                if message_type == "prompt_rules.set":
                    if "enabled" in payload and not isinstance(payload["enabled"], bool):
                        raise ValueError("Prompt rule enabled must be a boolean.")
                    rule = self.prompt_rules.set(
                        scope,
                        scope_id,
                        str(payload.get("content") or ""),
                        enabled=bool(payload.get("enabled", True)),
                    )
                    changed_payload = {
                        "scope": scope,
                        "scope_id": scope_id,
                        "rule": rule.to_dict(),
                        "reset": False,
                    }
                elif message_type == "prompt_rules.toggle":
                    if not isinstance(payload.get("enabled"), bool):
                        raise ValueError("Prompt rule enabled must be a boolean.")
                    rule = self.prompt_rules.toggle(
                        scope,
                        scope_id,
                        bool(payload["enabled"]),
                    )
                    changed_payload = {
                        "scope": scope,
                        "scope_id": scope_id,
                        "rule": rule.to_dict(),
                        "reset": False,
                    }
                else:
                    self.prompt_rules.reset(scope, scope_id)
                    changed_payload = {
                        "scope": scope,
                        "scope_id": scope_id,
                        "rule": None,
                        "reset": True,
                    }
            except ValueError as exc:
                await self.send_error(
                    ws,
                    "PROMPT_RULE_INVALID",
                    str(exc),
                    request_id=request_id,
                    thread_id=data.get("thread_id"),
                )
                return

            await ws.send_json(
                envelope(
                    "prompt_rules.changed",
                    changed_payload,
                    request_id=request_id,
                    thread_id=(scope_id if scope == "thread" else data.get("thread_id")),
                )
            )
            return

        if message_type == "mcp.list":
            await ws.send_json(
                envelope(
                    "mcp.listed",
                    self.mcp_runtime.public_payload(),
                    request_id=request_id,
                )
            )
            return

        if message_type in {
            "mcp.upsert",
            "mcp.delete",
            "mcp.refresh",
            "mcp.secrets",
        }:
            if any(not task.done() for task in self.active_turns.values()):
                await self.send_error(
                    ws,
                    "TURN_RUNNING",
                    "Stop the active turn before changing MCP configuration.",
                    request_id=request_id,
                )
                return

            try:
                if message_type == "mcp.upsert":
                    raw_config = payload.get("server")
                    if not isinstance(raw_config, dict):
                        raise ValueError("server must be an object.")
                    server_config = self.mcp_settings.upsert(raw_config)
                    await self.mcp_runtime.refresh()
                    result_payload = {
                        "server": server_config.to_public_dict(),
                        **self.mcp_runtime.public_payload(),
                    }
                    response_type = "mcp.changed"
                elif message_type == "mcp.delete":
                    server_id = str(payload.get("server_id") or "").strip()
                    if not server_id:
                        raise ValueError("server_id is required.")
                    self.mcp_settings.delete(server_id)
                    self.mcp_runtime.secret_env.pop(server_id, None)
                    await self.mcp_runtime.refresh()
                    result_payload = self.mcp_runtime.public_payload()
                    response_type = "mcp.changed"
                elif message_type == "mcp.secrets":
                    raw_secrets = payload.get("secrets")
                    if not isinstance(raw_secrets, dict):
                        raise ValueError("secrets must be an object.")
                    self.mcp_runtime.set_secrets(raw_secrets)
                    await self.mcp_runtime.refresh()
                    result_payload = self.mcp_runtime.public_payload()
                    response_type = "mcp.changed"
                else:
                    await self.mcp_runtime.refresh()
                    result_payload = self.mcp_runtime.public_payload()
                    response_type = "mcp.refreshed"
            except ValueError as exc:
                await self.send_error(
                    ws,
                    "MCP_CONFIG_INVALID",
                    str(exc),
                    request_id=request_id,
                )
                return
            except Exception as exc:
                self._record_diagnostic_error(
                    "MCP_RUNTIME_ERROR",
                    str(exc),
                    source="mcp",
                )
                await self.send_error(
                    ws,
                    "MCP_RUNTIME_ERROR",
                    str(exc),
                    request_id=request_id,
                )
                return

            await ws.send_json(
                envelope(
                    response_type,
                    result_payload,
                    request_id=request_id,
                )
            )
            return

        if message_type == "approval.respond":
            approval_id = str(payload.get("approval_id") or "")
            decision = str(payload.get("decision") or "")
            try:
                pending = self.approvals.respond(approval_id, decision)
            except ValueError as exc:
                await self.send_error(
                    ws,
                    "INVALID_APPROVAL_DECISION",
                    str(exc),
                    request_id=request_id,
                    turn_id=data.get("turn_id"),
                )
                return

            if not pending:
                await self.send_error(
                    ws,
                    "APPROVAL_NOT_FOUND",
                    "Approval request is no longer pending.",
                    request_id=request_id,
                    turn_id=data.get("turn_id"),
                )
                return

            await ws.send_json(
                envelope(
                    "approval.resolved",
                    {
                        "approval_id": approval_id,
                        "decision": decision,
                    },
                    request_id=request_id,
                    thread_id=pending.thread_id,
                    turn_id=pending.turn_id,
                )
            )
            return

        if message_type == "project.open":
            raw_path = str(payload.get("path") or "").strip()
            requested_model = str(payload.get("model") or "").strip() or None
            if not raw_path:
                await self.send_error(
                    ws,
                    "WORKSPACE_REQUIRED",
                    "Workspace path is required.",
                    request_id=request_id,
                )
                return
            if any(not task.done() for task in self.active_turns.values()):
                await self.send_error(
                    ws,
                    "TURN_RUNNING",
                    "Stop the active turn before changing workspace.",
                    request_id=request_id,
                )
                return
            try:
                project, thread, created = self.projects.open(
                    raw_path,
                    active_model=(
                        requested_model
                        or self.default_model
                        or self.provider.preferred_model
                    ),
                )
            except (ToolError, OSError) as exc:
                message = exc.message if isinstance(exc, ToolError) else str(exc)
                await self.send_error(
                    ws,
                    "WORKSPACE_OPEN_FAILED",
                    message,
                    request_id=request_id,
                )
                return

            project.workspace.set_full_access(
                self.permissions.mode == PermissionMode.FULL_ACCESS
            )
            self.mcp_runtime.apply_to_project(project)
            response_payload = self.projects.project_payload(project)
            response_payload["created"] = created
            await ws.send_json(
                envelope(
                    "project.opened",
                    response_payload,
                    request_id=request_id,
                    thread_id=thread.id,
                )
            )
            return

        if message_type == "project.list":
            await ws.send_json(
                envelope(
                    "project.listed",
                    {"projects": self.projects.list_payload()},
                    request_id=request_id,
                )
            )
            return

        if message_type == "project.select":
            if any(not task.done() for task in self.active_turns.values()):
                await self.send_error(
                    ws,
                    "TURN_RUNNING",
                    "Stop the active turn before switching projects.",
                    request_id=request_id,
                )
                return
            project_id = str(payload.get("project_id") or "").strip()
            selected = self.projects.select(
                project_id,
                active_model=(
                    str(payload.get("model") or "").strip()
                    or self.default_model
                    or self.provider.preferred_model
                ),
            )
            if not selected:
                await self.send_error(
                    ws,
                    "PROJECT_NOT_FOUND",
                    "Project is not open in this session.",
                    request_id=request_id,
                )
                return
            project, thread = selected
            project.workspace.set_full_access(
                self.permissions.mode == PermissionMode.FULL_ACCESS
            )
            self.mcp_runtime.apply_to_project(project)
            await ws.send_json(
                envelope(
                    "project.selected",
                    self.projects.project_payload(project),
                    request_id=request_id,
                    thread_id=thread.id,
                )
            )
            return

        if message_type == "project.get":
            project = self.projects.active
            await ws.send_json(
                envelope(
                    "project.loaded",
                    (
                        self.projects.project_payload(project)
                        if project
                        else {
                            "project": None,
                            "threads": [],
                            "active_thread": None,
                            "messages": [],
                        }
                    ),
                    request_id=request_id,
                )
            )
            return

        if message_type == "model.list":
            status = await self.provider.get_status()
            self.available_models = {
                str(item.get("name"))
                for item in status["models"]
                if isinstance(item, dict) and item.get("name")
            }
            if status.get("default_model"):
                self.default_model = str(status["default_model"])
            await ws.send_json(envelope("model.listed", status, request_id=request_id))
            return

        if message_type == "model.select":
            thread_id = str(data.get("thread_id") or payload.get("thread_id") or "")
            model = str(payload.get("model") or "").strip()
            project = self.projects.active
            thread = project.state.get_thread(thread_id) if project else None
            if not thread:
                await self.send_error(ws, "THREAD_NOT_FOUND", "Thread does not exist.", request_id=request_id, thread_id=thread_id or None)
                return
            if not model:
                await self.send_error(ws, "MODEL_REQUIRED", "Model name cannot be empty.", request_id=request_id, thread_id=thread_id)
                return
            if not await self.ensure_model_available(ws, model, request_id=request_id, thread_id=thread_id):
                return
            updated = project.state.set_thread_model(thread_id, model) if project else None
            await ws.send_json(
                envelope(
                    "model.selected",
                    {"model": model, "thread": updated.to_dict() if updated else None},
                    request_id=request_id,
                    thread_id=thread_id,
                )
            )
            return

        if message_type == "thread.create":
            project = self.projects.active
            if not project:
                await self.send_error(
                    ws,
                    "WORKSPACE_REQUIRED",
                    "Open a project before creating a coding thread.",
                    request_id=request_id,
                )
                return
            requested_model = str(payload.get("model") or "").strip() or None
            thread = project.state.create_thread(
                payload.get("title"),
                active_model=(
                    requested_model
                    or self.default_model
                    or self.provider.preferred_model
                ),
            )
            project.active_thread_id = thread.id
            project.touch()
            await ws.send_json(
                envelope(
                    "thread.created",
                    {
                        "thread": thread.to_dict(),
                        "project_id": project.id,
                    },
                    request_id=request_id,
                    thread_id=thread.id,
                )
            )
            return

        if message_type == "thread.list":
            project = self.projects.active
            await ws.send_json(
                envelope(
                    "thread.listed",
                    {
                        "project_id": project.id if project else None,
                        "threads": (
                            [item.to_dict() for item in project.state.list_threads()]
                            if project
                            else []
                        ),
                    },
                    request_id=request_id,
                )
            )
            return

        if message_type.startswith("plan."):
            project = self.projects.active
            thread_id = str(payload.get("thread_id") or data.get("thread_id") or
                            (project.active_thread_id if project else "") or "")
            if not project or not project.state.get_thread(thread_id):
                await self.send_error(ws, "THREAD_NOT_FOUND",
                                      "Open a valid thread to manage its plan.",
                                      request_id=request_id, thread_id=thread_id or None)
                return
            plans = self.store.task_plans
            try:
                plan_id = str(payload.get("plan_id") or "")
                if message_type == "plan.create":
                    plan_id = plans.create(thread_id, str(payload.get("goal") or ""),
                                           list(payload.get("steps") or []))
                elif message_type == "plan.step.update":
                    plan = plans.get(plan_id)
                    if plan["thread_id"] != thread_id:
                        raise ValueError("Plan belongs to another thread")
                    plans.update_step(plan_id, str(payload.get("step_id") or ""),
                                      str(payload.get("state") or ""),
                                      payload.get("evidence"))
                elif message_type == "plan.step.edit":
                    plan = plans.get(plan_id)
                    if plan["thread_id"] != thread_id:
                        raise ValueError("Plan belongs to another thread")
                    plans.edit_step(plan_id, str(payload.get("step_id") or ""),
                                    str(payload.get("description") or ""),
                                    str(payload.get("verification") or ""))
                elif message_type == "plan.steps.reorder":
                    plan = plans.get(plan_id)
                    if plan["thread_id"] != thread_id:
                        raise ValueError("Plan belongs to another thread")
                    plans.reorder_steps(plan_id, list(payload.get("step_ids") or []))
                elif message_type == "plan.checkpoint":
                    plan = plans.get(plan_id)
                    if plan["thread_id"] != thread_id:
                        raise ValueError("Plan belongs to another thread")
                    plans.checkpoint(plan_id, "manual")
                elif message_type == "plan.resume":
                    plan = plans.get(plan_id)
                    if plan["thread_id"] != thread_id:
                        raise ValueError("Plan belongs to another thread")
                    await ws.send_json(envelope(
                        "plan.resumable", plans.prepare_resume(plan_id),
                        request_id=request_id, thread_id=thread_id))
                    return
                elif message_type != "plan.list":
                    raise ValueError("Unsupported plan operation")
                await ws.send_json(envelope(
                    "plan.loaded", {"plans": plans.list_for_thread(thread_id)},
                    request_id=request_id, thread_id=thread_id))
            except (ValueError, KeyError, TypeError) as exc:
                await self.send_error(ws, "PLAN_INVALID", str(exc),
                                      request_id=request_id, thread_id=thread_id)
            return

        if message_type == "thread.get":
            thread_id = str(payload.get("thread_id") or data.get("thread_id") or "")
            project = self.projects.active
            thread = project.state.get_thread(thread_id) if project else None
            if not thread:
                await self.send_error(ws, "THREAD_NOT_FOUND", "Thread does not exist.", request_id=request_id, thread_id=thread_id or None)
                return
            self.projects.mark_active_thread(thread.id)
            await ws.send_json(
                envelope(
                    "thread.loaded",
                    {
                        "thread": thread.to_dict(),
                        "messages": project.state.get_messages(thread.id),
                        "project_id": project.id,
                    },
                    request_id=request_id,
                    thread_id=thread.id,
                )
            )
            return

        if message_type == "turn.start":
            thread_id = str(data.get("thread_id") or payload.get("thread_id") or "")
            prompt = str(payload.get("prompt") or "").strip()
            project = self.projects.active
            thread = project.state.get_thread(thread_id) if project else None

            if not project:
                await self.send_error(ws, "WORKSPACE_REQUIRED", "Open a project before starting a coding turn.", request_id=request_id, thread_id=thread_id or None)
                return
            if not thread:
                await self.send_error(ws, "THREAD_NOT_FOUND", "Create or load a thread before starting a turn.", request_id=request_id, thread_id=thread_id or None)
                return
            if not prompt:
                await self.send_error(ws, "EMPTY_PROMPT", "Prompt cannot be empty.", request_id=request_id, thread_id=thread_id)
                return

            model = thread.active_model or self.default_model or self.provider.preferred_model
            if not await self.ensure_model_available(ws, model, request_id=request_id, thread_id=thread_id):
                return

            turn_id = new_id("turn")
            project.state.touch_thread(thread_id)
            self.projects.mark_active_thread(thread_id)
            await ws.send_json(
                envelope(
                    "turn.started",
                    {
                        "prompt": prompt,
                        "model": model,
                        "provider": self.provider.provider_name,
                        "workspace": project.workspace.display_path,
                        "project_id": project.id,
                    },
                    request_id=request_id,
                    thread_id=thread_id,
                    turn_id=turn_id,
                )
            )

            task = asyncio.create_task(
                self.run_tool_turn(
                    ws,
                    thread_id=thread_id,
                    turn_id=turn_id,
                    prompt=prompt,
                    model=model,
                ),
                name=turn_id,
            )
            self.active_turns[turn_id] = task
            owned_turns.add(turn_id)
            task.add_done_callback(lambda _task, tid=turn_id: self.active_turns.pop(tid, None))
            return

        if message_type == "turn.cancel":
            turn_id = str(data.get("turn_id") or payload.get("turn_id") or "")
            task = self.active_turns.get(turn_id)
            if not task or task.done():
                await self.send_error(ws, "TURN_NOT_RUNNING", "Turn is not running.", request_id=request_id, turn_id=turn_id or None)
                return
            self.approvals.cancel_turn(turn_id)
            task.cancel()
            return

        await self.send_error(
            ws,
            "UNKNOWN_MESSAGE_TYPE",
            f"Unsupported message type: {message_type}",
            request_id=request_id,
        )

    def _resolve_prompt_rule_scope_id(
        self,
        scope: str,
        payload: dict[str, Any],
        data: dict[str, Any],
    ) -> str | None:
        normalized_scope = str(scope or "").strip().lower()
        if normalized_scope == "global":
            return None

        project = self.projects.active
        if normalized_scope == "project":
            requested_project_id = str(payload.get("project_id") or "").strip()
            project_id = requested_project_id or (project.id if project else "")
            if not project_id or not self.projects.get(project_id):
                raise ValueError("Open a valid project before editing project Prompt Rules.")
            return project_id

        if normalized_scope == "thread":
            thread_id = str(
                payload.get("thread_id")
                or data.get("thread_id")
                or ""
            ).strip()
            if not project or not thread_id or not project.state.get_thread(thread_id):
                raise ValueError(
                    "Open a valid thread in the active project before editing Thread Prompt Rules."
                )
            return thread_id

        raise ValueError(
            "Prompt rule scope must be one of: global, project, thread."
        )

    def _system_prompt(
        self,
        *,
        project_id: str,
        thread_id: str,
        workspace_path: str,
        project_detection: str | None = None,
    ) -> str:
        parts = [SYSTEM_PROMPT]
        rule_block = self.prompt_rules.render_effective(
            project_id=project_id,
            thread_id=thread_id,
        )
        if rule_block:
            parts.append(rule_block)
        if project_detection:
            parts.append(project_detection)
        parts.append("Current workspace: " + workspace_path)
        parts.append(self._permission_prompt())
        return "\n\n".join(parts)

    def _exact_secrets(self) -> tuple[str, ...]:
        return tuple(
            secret
            for secret in (
                self.openai_api_key,
                *self.mcp_runtime.exact_secrets(),
            )
            if secret
        )

    def _record_diagnostic_error(
        self,
        code: str,
        message: str,
        *,
        source: str,
    ) -> None:
        exact_secrets = self._exact_secrets()
        self.recent_errors.append(
            {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "source": source,
                "code": str(code),
                "message": redact_text(
                    message,
                    exact_secrets=exact_secrets,
                    max_chars=300,
                ),
            }
        )

    async def _diagnostics_payload(self) -> dict[str, Any]:
        exact_secrets = self._exact_secrets()
        try:
            provider_status = await self.provider.get_status()
        except Exception as exc:
            self._record_diagnostic_error(
                "DIAGNOSTICS_PROVIDER_STATUS",
                str(exc),
                source="diagnostics",
            )
            provider_status = {
                "provider": self.provider.provider_name,
                "online": False,
                "base_url": getattr(self.provider, "base_url", ""),
                "models": [],
                "default_model": None,
                "preferred_model": self.provider.preferred_model,
                "context_window": self.provider.context_window,
                "error": {
                    "code": "DIAGNOSTICS_PROVIDER_STATUS",
                    "message": str(exc),
                },
            }

        project = self.projects.active
        project_payload: dict[str, Any] | None = None
        prompt_rules = {
            "global": {"configured": False, "enabled": False},
            "project": {"configured": False, "enabled": False},
            "thread": {"configured": False, "enabled": False},
        }
        if project:
            detection = project.detection()
            project_payload = {
                "name": project.name,
                "path": redact_path(project.path),
                "thread_count": len(project.state.list_threads()),
                "active_thread": bool(project.active_thread_id),
                "detection": detection.to_dict(),
            }
            prompt_rules = prompt_rules_summary(
                self.prompt_rules.hierarchy(
                    project_id=project.id,
                    thread_id=project.active_thread_id,
                )
            )
        else:
            prompt_rules = prompt_rules_summary(
                self.prompt_rules.hierarchy(
                    project_id=None,
                    thread_id=None,
                )
            )

        return {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "application": {
                "version": APP_VERSION,
                "protocol": PROTOCOL_VERSION,
            },
            "runtime": {
                "python": sys.version.split()[0],
                "platform": platform.system(),
                "platform_release": platform.release(),
                "architecture": platform.machine(),
            },
            "provider": sanitize_provider_status(
                provider_status,
                exact_secrets=exact_secrets,
            ),
            "context": {
                "window_tokens": self.provider.context_window,
                "reserved_output_tokens": self.context_reserved_output_tokens,
                "last_usage": self.last_context_usage,
            },
            "permission": {
                "mode": self.permissions.mode.value,
            },
            "workspace": project_payload,
            "prompt_rules": prompt_rules,
            "mcp": self.mcp_runtime.diagnostic_payload(),
            "database": database_summary(self.store),
            "agent_limits": {
                "max_model_steps": self.max_model_steps,
                "max_tool_calls": self.max_tool_calls,
                "max_blocked_repeats": self.max_blocked_repeats,
                "max_consecutive_tool_failures": (
                    self.max_consecutive_tool_failures
                ),
                "model_retry_attempts": self.model_retry_attempts,
            },
            "recent_errors": list(self.recent_errors),
            "redaction": {
                "api_keys": True,
                "mcp_credentials": True,
                "prompt_rule_content": True,
                "chat_history": True,
                "home_path": True,
            },
        }

    def _settings_payload(self) -> dict[str, Any]:
        configured_key = self.openai_api_key
        if configured_key is None:
            configured_key = os.getenv("LCA_OPENAI_API_KEY", "")
        return self.settings.to_public_dict(
            api_key_configured=bool(configured_key),
        )

    def _apply_runtime_settings(
        self,
        settings: RuntimeSettings,
    ) -> None:
        self.settings = settings
        self.provider = settings.create_provider(
            openai_api_key=self.openai_api_key,
        )
        self.max_model_steps = settings.max_model_steps
        self.max_tool_calls = settings.max_tool_calls
        self.max_blocked_repeats = settings.max_blocked_repeats
        self.max_consecutive_tool_failures = (
            settings.max_consecutive_tool_failures
        )
        self.model_retry_attempts = settings.model_retry_attempts
        self.context_reserved_output_tokens = (
            settings.context_reserved_output_tokens
        )
        self.available_models.clear()
        self.default_model = self.provider.preferred_model or None

    def _sync_workspace_permissions(self) -> None:
        full_access = self.permissions.mode == PermissionMode.FULL_ACCESS
        for project in self.projects.list_projects():
            project.workspace.set_full_access(full_access)

    def _permission_prompt(self) -> str:
        mode = self.permissions.mode
        if mode == PermissionMode.READ_ONLY:
            return (
                "Permission mode: Read Only. You can inspect files and Git state, "
                "but you cannot modify files or run shell commands."
            )
        if mode == PermissionMode.FULL_ACCESS:
            return (
                "Permission mode: Full Access. Workspace operations are available. "
                "Absolute paths outside the workspace may be used only when needed and "
                "will require explicit user approval. Risky commands also require approval."
            )
        return (
            "Permission mode: Workspace. You can read/write inside the active workspace "
            "and run development commands there. Risky/destructive/publishing commands "
            "require explicit user approval. Access outside the workspace is denied."
        )

    async def ensure_model_available(
        self,
        ws: web.WebSocketResponse,
        model: str,
        *,
        request_id: str | None,
        thread_id: str | None,
    ) -> bool:
        if not self.available_models:
            status = await self.provider.get_status()
            if not status["online"]:
                error = status.get("error") or {}
                await self.send_error(
                    ws,
                    str(error.get("code") or "PROVIDER_UNAVAILABLE"),
                    str(error.get("message") or "The selected model provider is unavailable."),
                    request_id=request_id,
                    thread_id=thread_id,
                )
                return False
            self.available_models = {
                str(item.get("name"))
                for item in status["models"]
                if isinstance(item, dict) and item.get("name")
            }
        if model not in self.available_models:
            await self.send_error(
                ws,
                "MODEL_NOT_FOUND",
                f"Model is not available from {self.provider.provider_name}: {model}",
                request_id=request_id,
                thread_id=thread_id,
            )
            return False
        return True

    def _checkpoint_thread_plans(self, thread_id: str, reason: str,
                                 files_changed: list[str] | None = None,
                                 commands_run: list[dict] | None = None) -> None:
        """Persist active plans on turn boundaries without replaying tools."""
        plans = self.store.task_plans
        for plan in plans.list_for_thread(thread_id):
            if any(step["state"] in ("pending", "in_progress", "blocked")
                   for step in plan["steps"]):
                plans.checkpoint(plan["id"], reason, files_changed=files_changed, commands_run=commands_run)

    async def run_tool_turn(
        self,
        ws: web.WebSocketResponse,
        *,
        thread_id: str,
        turn_id: str,
        prompt: str,
        model: str,
    ) -> None:
        project = self.projects.active
        if not project:
            return

        workspace = project.workspace
        workspace.set_full_access(
            self.permissions.mode == PermissionMode.FULL_ACCESS
        )
        tools = project.tools
        state = project.state
        guard = ToolLoopGuard()
        plan_files_changed: set[str] = set()
        plan_commands_run: list[dict] = []
        plan_tool_evidence: list[dict] = []


        active_plans = [
            plan for plan in self.store.task_plans.list_for_thread(thread_id)
            if any(item["state"] in ("pending", "in_progress", "blocked") for item in plan["steps"])
        ]
        # Existing plans are explicit user intent. Do not create plans for simple turns.
        active_plan = active_plans[0] if active_plans else None
        active_step_id: str | None = None
        if active_plan:
            first_step = self.store.task_plans.active_step(active_plan["id"])
            if first_step and first_step["state"] != "blocked":
                active_step_id = first_step["id"]

        history = state.get_messages(thread_id)
        context_manager = ContextBudgetManager(
            context_window_tokens=self.provider.context_window,
            reserved_output_tokens=self.context_reserved_output_tokens,
        )
        pinned_rows = self.store.list_pinned_context(thread_id)
        pinned_paths = [str(row["path"]) for row in pinned_rows]
        mention_paths = extract_file_mentions(prompt)
        pinned_set = set(pinned_paths)
        mentioned_files = [
            load_context_file(
                workspace,
                path,
                source="mentioned_file",
            )
            for path in mention_paths
            if path not in pinned_set
        ]
        pinned_files = [
            load_context_file(
                workspace,
                path,
                source="pinned_file",
            )
            for path in pinned_paths
        ]
        context_blocks = [
            *([{
                "source": "task_plan",
                "content": (
                    "Persistent task plan (user-authored; follow these steps in order). "
                    "Do not claim completion without real tool evidence. "
                    "Never repeat mutating tools merely because a checkpoint exists.\n"
                    + "\n".join(
                        f'{index + 1}. [{item["state"]}] {item["description"]} '
                        f'(verify: {item["verification"]})'
                        for index, item in enumerate(active_plan["steps"])
                    )
                ),
            }] if active_plan else []),
            *context_blocks_for_files(mentioned_files),
            *context_blocks_for_files(pinned_files),
            {
                "source": "repo_map",
                "content": project.ensure_repository_map().render(),
            },
        ]
        unavailable = [
            item
            for item in [*mentioned_files, *pinned_files]
            if item.status != "ready"
        ]
        if unavailable:
            context_blocks.insert(
                0,
                {
                    "source": "explicit_context_status",
                    "content": (
                        "Some explicitly selected workspace files are unavailable:\n"
                        + "\n".join(
                            f"- {item.path}: {item.status}"
                            for item in unavailable
                        )
                    ),
                },
            )

        initial_context = context_manager.prepare_initial(
            system_prompt=self._system_prompt(
                project_id=project.id,
                thread_id=thread_id,
                workspace_path=workspace.display_path,
                project_detection=project.detection().prompt_text(),
            ),
            history=history,
            user_prompt=prompt,
            context_blocks=context_blocks,
        )
        messages: list[dict[str, Any]] = initial_context.messages
        context_usage = initial_context.usage
        context_source_tokens = dict(context_usage.context_sources)
        self.last_context_usage = context_usage.to_dict()

        await ws.send_json(
            envelope(
                "context.updated",
                context_usage.to_dict(),
                thread_id=thread_id,
                turn_id=turn_id,
            )
        )

        prompt_eval_count: int | None = None
        eval_count: int | None = None
        total_tool_calls = 0

        try:
            for step in range(1, self.max_model_steps + 1):
                assistant_parts: list[str] = []
                tool_calls: list[ToolCall] = []
                step_tool_keys: set[str] = set()
                finish_reason: str | None = None
                observed_output = False

                for attempt in range(1, self.model_retry_attempts + 1):
                    try:
                        fitted_context = context_manager.fit_runtime(
                            messages,
                            history_messages_total=len(history),
                            context_sources=context_source_tokens,
                        )
                        messages = fitted_context.messages
                        context_usage = fitted_context.usage
                        self.last_context_usage = context_usage.to_dict()
                        await ws.send_json(
                            envelope(
                                "context.updated",
                                context_usage.to_dict(),
                                thread_id=thread_id,
                                turn_id=turn_id,
                            )
                        )

                        async for chunk in self.provider.stream_chat(
                            model=model,
                            messages=messages,
                            tools=tools.schemas(
                                self.permissions.visible_tools(
                                    tools.names,
                                    tools.permission_metadata_map(),
                                )
                            ),
                        ):
                            if chunk.content:
                                observed_output = True
                                assistant_parts.append(chunk.content)
                                await ws.send_json(
                                    envelope(
                                        "turn.delta",
                                        {"delta": chunk.content},
                                        thread_id=thread_id,
                                        turn_id=turn_id,
                                    )
                                )

                            if chunk.tool_calls:
                                observed_output = True
                                for call in chunk.tool_calls:
                                    key = canonical_tool_fingerprint(
                                        call.name,
                                        call.arguments,
                                    )
                                    if key not in step_tool_keys:
                                        step_tool_keys.add(key)
                                        tool_calls.append(call)

                            if chunk.done:
                                finish_reason = chunk.finish_reason
                                prompt_eval_count = chunk.prompt_eval_count
                                eval_count = chunk.eval_count
                        break
                    except ProviderError as exc:
                        can_retry = (
                            exc.transient
                            and not observed_output
                            and attempt < self.model_retry_attempts
                        )
                        if not can_retry:
                            raise

                        await ws.send_json(
                            envelope(
                                "turn.status",
                                {
                                    "phase": "model_retry",
                                    "message": (
                                        "Model provider connection failed before producing output; "
                                        f"retrying ({attempt}/{self.model_retry_attempts - 1})."
                                    ),
                                },
                                thread_id=thread_id,
                                turn_id=turn_id,
                            )
                        )
                        await asyncio.sleep(0.5 * attempt)

                assistant_text = "".join(assistant_parts)

                if not tool_calls:
                    gaps = guard.completion_gaps()
                    verification = {
                        "complete": not gaps,
                        "missing": gaps,
                        "changed_paths": sorted(guard.changed_paths),
                    }

                    state.append_exchange(
                        thread_id,
                        user=prompt,
                        assistant=assistant_text,
                    )

                    if active_plan and active_step_id:
                        evidence = [item for item in plan_tool_evidence
                                    if item.get("step_id") == active_step_id]
                        # A step declaring verification cannot be completed
                        # solely by reading a file or reporting tool success.
                        current_step = self.store.task_plans.active_step(active_plan["id"])
                        requires_check = bool(current_step and
                                              current_step["id"] == active_step_id and
                                              current_step["verification"].strip())
                        passed_checks = any(
                            command.get("ok") is True for command in plan_commands_run
                        )
                        self.store.task_plans.advance_verified(
                            active_plan["id"], active_step_id, evidence,
                            not gaps and (not requires_check or passed_checks))
                    self._checkpoint_thread_plans(thread_id, "turn_completed", sorted(plan_files_changed), plan_commands_run)
                    await ws.send_json(
                        envelope(
                            "turn.completed",
                            {
                                "finish_reason": finish_reason or "stop",
                                "provider": self.provider.provider_name,
                                "model": model,
                                "context_window": self.provider.context_window,
                                "prompt_eval_count": prompt_eval_count,
                                "eval_count": eval_count,
                                "context": context_usage.to_dict(),
                                "model_steps": step,
                                "tool_calls": total_tool_calls,
                                "verification": verification,
                            },
                            thread_id=thread_id,
                            turn_id=turn_id,
                        )
                    )
                    return

                messages.append(
                    {
                        "role": "assistant",
                        "content": assistant_text,
                        "tool_calls": [
                            {
                                **({"id": call.id} if call.id else {}),
                                "type": "function",
                                "function": {
                                    "name": call.name,
                                    "arguments": call.arguments,
                                },
                            }
                            for call in tool_calls
                        ],
                    }
                )

                for call_index, call in enumerate(tool_calls, start=1):
                    total_tool_calls += 1
                    if total_tool_calls > self.max_tool_calls:
                        self._record_diagnostic_error(
                            "MAX_TOOL_CALLS",
                            f"Agent exceeded {self.max_tool_calls} tool calls without completing the task.",
                            source="agent_loop",
                        )
                        await ws.send_json(
                            envelope(
                                "turn.failed",
                                {
                                    "code": "MAX_TOOL_CALLS",
                                    "message": (
                                        f"Agent exceeded {self.max_tool_calls} tool calls "
                                        "without completing the task."
                                    ),
                                    "recoverable": True,
                                    "provider": self.provider.provider_name,
                                    "model": model,
                                    "tool_calls": total_tool_calls,
                                },
                                thread_id=thread_id,
                                turn_id=turn_id,
                            )
                        )
                        return

                    call_id = f"{turn_id}:{step}:{call_index}"
                    allowed, repeat_count, _ = guard.register_call(
                        call.name,
                        call.arguments,
                    )

                    await ws.send_json(
                        envelope(
                            "tool.requested",
                            {
                                "tool_call_id": call_id,
                                "name": call.name,
                                "arguments": call.arguments,
                                "repeat_count": repeat_count,
                            },
                            thread_id=thread_id,
                            turn_id=turn_id,
                        )
                    )
                    await ws.send_json(
                        envelope(
                            "tool.started",
                            {
                                "tool_call_id": call_id,
                                "name": call.name,
                                "arguments": call.arguments,
                            },
                            thread_id=thread_id,
                            turn_id=turn_id,
                        )
                    )

                    if not allowed:
                        if guard.last_block_reason and guard.last_block_reason.startswith(
                            "cycle:"
                        ):
                            cycle_length = guard.last_block_reason.split(":", 1)[1]
                            payload = {
                                "ok": False,
                                "summary": (
                                    "Short tool-call cycle blocked before execution "
                                    f"(cycle length {cycle_length})."
                                ),
                                "error": {
                                    "code": "REPEATED_TOOL_CYCLE",
                                    "message": (
                                        "The Agent is alternating between the same tool calls "
                                        "without making progress. Change approach instead of "
                                        "continuing the cycle."
                                    ),
                                },
                                "changed_paths": [],
                            }
                        else:
                            payload = {
                                "ok": False,
                                "summary": (
                                    "Identical tool call blocked because it was already "
                                    f"attempted {repeat_count - 1} times without new arguments."
                                ),
                                "error": {
                                    "code": "REPEATED_TOOL_CALL",
                                    "message": (
                                        "Do not repeat the same tool with the same arguments. "
                                        "Use the existing result or change approach."
                                    ),
                                },
                                "changed_paths": [],
                            }
                    else:
                        verdict = self.permissions.evaluate(
                            tool_name=call.name,
                            arguments=call.arguments,
                            workspace=workspace,
                            tool_metadata=tools.permission_metadata(
                                call.name
                            ),
                            user_prompt=prompt,
                        )

                        if not verdict.allowed:
                            payload = {
                                "ok": False,
                                "summary": verdict.reason,
                                "error": {
                                    "code": "PERMISSION_DENIED",
                                    "message": verdict.reason,
                                    "risk": verdict.risk,
                                },
                                "changed_paths": [],
                            }
                        else:
                            approved = True
                            if verdict.requires_approval:
                                decision = await self.approvals.request(
                                    ws,
                                    turn_id=turn_id,
                                    thread_id=thread_id,
                                    approval_key=verdict.approval_key or call_id,
                                    tool_name=call.name,
                                    arguments=call.arguments,
                                    reason=verdict.reason,
                                    risk=verdict.risk,
                                )
                                approved = decision != APPROVAL_DENY

                            if not approved:
                                payload = {
                                    "ok": False,
                                    "summary": "User denied this operation.",
                                    "error": {
                                        "code": "APPROVAL_DENIED",
                                        "message": "User denied this operation.",
                                        "risk": verdict.risk,
                                    },
                                    "changed_paths": [],
                                }
                            else:
                                payload = await self._execute_tool_call(
                                    ws,
                                    tools=tools,
                                    call=call,
                                    call_id=call_id,
                                    thread_id=thread_id,
                                    turn_id=turn_id,
                                )

                    if active_plan and payload.get("ok"):
                        # Do not silently skip a blocked step, even after a
                        # subsequent tool succeeds in the same model turn.
                        current_step = self.store.task_plans.active_step(active_plan["id"])
                        if current_step and current_step["state"] == "blocked":
                            active_step_id = None
                        elif current_step:
                            active_step_id = current_step["id"]
                            if current_step["state"] == "pending":
                                self.store.task_plans.update_step(
                                    active_plan["id"], active_step_id, "in_progress")
                        if active_step_id:
                            plan_tool_evidence.append({
                                "step_id": active_step_id, "tool": call.name,
                                "ok": True, "summary": str(payload.get("summary", ""))[:500],
                                "changed_paths": list(payload.get("changed_paths") or []),
                            })
                    if call.name in ("shell", "shell_exec", "run_command", "run_shell"):
                        plan_commands_run.append({
                            "tool": call.name, "arguments": call.arguments,
                            "ok": bool(payload.get("ok")),
                            "summary": str(payload.get("summary", ""))[:500],
                        })
                    plan_files_changed.update(str(p) for p in (payload.get("changed_paths") or []))
                    if active_plan and active_step_id and not payload.get("ok"):
                        self.store.task_plans.update_step(active_plan["id"], active_step_id, "blocked")
                        active_step_id = None
                    guard.record_result(call.name, payload)

                    failure_limit_reached = guard.failure_limit_reached(
                        max_consecutive_failures=self.max_consecutive_tool_failures
                    )
                    loop_abort_reason = guard.loop_abort_reason(
                        max_blocked_repeats=self.max_blocked_repeats
                    )

                    await ws.send_json(
                        envelope(
                            "tool.completed",
                            {
                                "tool_call_id": call_id,
                                "name": call.name,
                                "result": payload,
                            },
                            thread_id=thread_id,
                            turn_id=turn_id,
                        )
                    )

                    changed_paths = [
                        str(path)
                        for path in (payload.get("changed_paths") or [])
                    ]
                    if changed_paths:
                        project.refresh_repository_paths(changed_paths)

                    for changed_path in changed_paths:
                        await ws.send_json(
                            envelope(
                                "file.changed",
                                {
                                    "path": changed_path,
                                    "tool_call_id": call_id,
                                },
                                thread_id=thread_id,
                                turn_id=turn_id,
                            )
                        )

                    messages.append(
                        {
                            "role": "tool",
                            **({"tool_call_id": call.id} if call.id else {}),
                            "name": call.name,
                            "tool_name": call.name,
                            "content": json.dumps(
                                compact_tool_payload(payload),
                                ensure_ascii=False,
                            ),
                        }
                    )

                    if failure_limit_reached:
                        self._record_diagnostic_error(
                            "TOOL_FAILURE_LIMIT",
                            (
                                "Agent hit the consecutive tool failure limit "
                                f"({self.max_consecutive_tool_failures})."
                            ),
                            source="agent_loop",
                        )
                        await ws.send_json(
                            envelope(
                                "turn.failed",
                                {
                                    "code": "TOOL_FAILURE_LIMIT",
                                    "message": (
                                        "Agent hit the consecutive tool failure limit "
                                        f"({self.max_consecutive_tool_failures}). "
                                        "The turn was stopped instead of continuing to fail."
                                    ),
                                    "recoverable": True,
                                    "provider": self.provider.provider_name,
                                    "model": model,
                                    "tool_calls": total_tool_calls,
                                    "consecutive_failures": guard.consecutive_failures,
                                    "last_failure_code": guard.last_failure_code,
                                },
                                thread_id=thread_id,
                                turn_id=turn_id,
                            )
                        )
                        return

                    if loop_abort_reason:
                        detail = (
                            "Agent entered a repeating short tool-call cycle."
                            if loop_abort_reason == "short_cycle"
                            else "Agent repeatedly requested identical tool calls."
                        )
                        self._record_diagnostic_error(
                            "TOOL_LOOP_DETECTED",
                            detail,
                            source="agent_loop",
                        )
                        await ws.send_json(
                            envelope(
                                "turn.failed",
                                {
                                    "code": "TOOL_LOOP_DETECTED",
                                    "message": (
                                        detail
                                        + " The turn was stopped to prevent an unproductive loop."
                                    ),
                                    "recoverable": True,
                                    "provider": self.provider.provider_name,
                                    "model": model,
                                    "tool_calls": total_tool_calls,
                                    "loop_reason": loop_abort_reason,
                                },
                                thread_id=thread_id,
                                turn_id=turn_id,
                            )
                        )
                        return

                note = guard.completion_note()
                if note and not guard.completion_reminder_sent:
                    guard.completion_reminder_sent = True
                    messages.append(
                        {
                            "role": "system",
                            "content": note,
                        }
                    )
                    await ws.send_json(
                        envelope(
                            "turn.status",
                            {
                                "phase": "verification",
                                "message": (
                                    "Changes detected. Agent is being asked to inspect the "
                                    "latest diff and validate code changes before finishing."
                                ),
                                "missing": guard.completion_gaps(),
                            },
                            thread_id=thread_id,
                            turn_id=turn_id,
                        )
                    )

            self._checkpoint_thread_plans(thread_id, "max_model_steps", sorted(plan_files_changed), plan_commands_run)
            self._record_diagnostic_error(
                "MAX_MODEL_STEPS",
                f"Agent exceeded {self.max_model_steps} model steps without completing the task.",
                source="agent_loop",
            )
            await ws.send_json(
                envelope(
                    "turn.failed",
                    {
                        "code": "MAX_MODEL_STEPS",
                        "message": (
                            f"Agent exceeded {self.max_model_steps} model steps "
                            "without completing the task."
                        ),
                        "recoverable": True,
                        "provider": self.provider.provider_name,
                        "model": model,
                    },
                    thread_id=thread_id,
                    turn_id=turn_id,
                )
            )
        except asyncio.CancelledError:
            self._checkpoint_thread_plans(thread_id, "turn_cancelled", sorted(plan_files_changed), plan_commands_run)
            with suppress(ConnectionResetError, RuntimeError):
                await ws.send_json(
                    envelope(
                        "turn.cancelled",
                        {
                            "reason": "user_cancelled",
                            "provider": self.provider.provider_name,
                            "model": model,
                        },
                        thread_id=thread_id,
                        turn_id=turn_id,
                    )
                )
            raise
        except ProviderError as exc:
            self._checkpoint_thread_plans(thread_id, "provider_error", sorted(plan_files_changed), plan_commands_run)
            self._record_diagnostic_error(
                exc.code,
                exc.message,
                source="provider",
            )
            with suppress(ConnectionResetError, RuntimeError):
                await ws.send_json(
                    envelope(
                        "turn.failed",
                        {
                            "code": exc.code,
                            "message": exc.message,
                            "recoverable": exc.recoverable,
                            "provider": self.provider.provider_name,
                            "model": model,
                        },
                        thread_id=thread_id,
                        turn_id=turn_id,
                    )
                )
        except (ConnectionResetError, RuntimeError):
            return
        finally:
            self.approvals.finish_turn(turn_id)

    async def _execute_tool_call(
        self,
        ws: web.WebSocketResponse,
        *,
        tools,
        call: ToolCall,
        call_id: str,
        thread_id: str,
        turn_id: str,
    ) -> dict[str, Any]:
        async def on_output(chunk: dict[str, Any]) -> None:
            await ws.send_json(
                envelope(
                    "tool.output",
                    {
                        "tool_call_id": call_id,
                        "name": call.name,
                        **chunk,
                    },
                    thread_id=thread_id,
                    turn_id=turn_id,
                )
            )

        try:
            result = await tools.execute(
                call.name,
                call.arguments,
                on_output=on_output,
            )
            return result.to_dict()
        except ToolError as exc:
            self._record_diagnostic_error(
                exc.code,
                exc.message,
                source="tool:" + call.name,
            )
            return {
                "ok": False,
                "summary": exc.message,
                "error": {
                    "code": exc.code,
                    "message": exc.message,
                },
                "changed_paths": [],
            }
        except Exception as exc:
            self._record_diagnostic_error(
                "TOOL_INTERNAL_ERROR",
                str(exc),
                source="tool:" + call.name,
            )
            return {
                "ok": False,
                "summary": f"Tool failed: {exc}",
                "error": {
                    "code": "TOOL_INTERNAL_ERROR",
                    "message": str(exc),
                },
                "changed_paths": [],
            }

    async def close_async(self) -> None:
        await self.mcp_runtime.close()

    def close(self) -> None:
        self.store.close()

    async def send_error(
        self,
        ws: web.WebSocketResponse,
        code: str,
        message: str,
        *,
        request_id: str | None = None,
        thread_id: str | None = None,
        turn_id: str | None = None,
    ) -> None:
        self._record_diagnostic_error(
            code,
            message,
            source="protocol",
        )
        await ws.send_json(
            envelope(
                "error",
                {
                    "code": code,
                    "message": message,
                    "recoverable": True,
                },
                request_id=request_id,
                thread_id=thread_id,
                turn_id=turn_id,
            )
        )


async def run(host: str, port: int) -> None:
    token = secrets.token_urlsafe(24)
    server = AgentServer(token)
    app = web.Application()
    stop_event = asyncio.Event()
    app["stop_event"] = stop_event
    app.router.add_get("/health", server.health)
    app.router.add_post("/shutdown", server.shutdown)
    app.router.add_get("/ws", server.websocket)

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, host, port)
    await site.start()

    sockets = getattr(site._server, "sockets", None)
    if not sockets:
        raise RuntimeError("Agent Server did not expose a listening socket.")
    bound_port = int(sockets[0].getsockname()[1])

    ready = {
        "host": host,
        "port": bound_port,
        "token": token,
        "version": APP_VERSION,
        "protocol": PROTOCOL_VERSION,
    }
    print("LCA_AGENT_READY " + json.dumps(ready), flush=True)

    try:
        await stop_event.wait()
    finally:
        tasks = list(server.active_turns.values())
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        await runner.cleanup()
        await server.close_async()
        server.close()
        print("LCA_AGENT_STOPPED", flush=True)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Local Coding Agent server")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=0)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    asyncio.run(run(args.host, args.port))


if __name__ == "__main__":
    main()
