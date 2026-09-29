from __future__ import annotations

import argparse
import asyncio
import json
import secrets
from contextlib import suppress
from typing import Any

from aiohttp import WSMsgType, web

from agent.core.agent_loop import (
    ToolLoopGuard,
    canonical_tool_fingerprint,
    compact_tool_payload,
    trim_history,
)
from agent.core.version import APP_VERSION, PROTOCOL_VERSION
from agent.llm.base import ToolCall
from agent.llm.ollama import OllamaProvider, OllamaProviderError
from agent.server.projects import ProjectRegistry
from agent.server.protocol import envelope, new_id, validate_client_message
from agent.tools.base import ToolError


SYSTEM_PROMPT = """You are Local Coding Agent, a local software-development agent.

When a workspace is open, you have tools to inspect and modify only that workspace.
Work deliberately:
- inspect the project before editing;
- do not invent file contents or command results;
- prefer small precise edits;
- use apply_patch for small edits and write_file for new/full-file content;
- run relevant tests or build commands after changes;
- inspect git_status/git_diff before declaring completion;
- if a command fails, analyze its real output before deciding the next step;
- never claim a test passed unless the tool result actually shows success.

Phase 4 blocks destructive commands such as bulk deletion, git reset --hard, git clean and git push.
Do not try to bypass those restrictions.

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


class AgentServer:
    MAX_MODEL_STEPS = 16
    MAX_TOOL_CALLS = 40
    MAX_BLOCKED_REPEATS = 3
    MODEL_RETRY_ATTEMPTS = 2

    def __init__(self, token: str) -> None:
        self.token = token
        self.projects = ProjectRegistry()
        self.provider = OllamaProvider()
        self.active_turns: dict[str, asyncio.Task[None]] = {}
        self.available_models: set[str] = set()
        self.default_model: str | None = self.provider.preferred_model

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

        return ws

    def _server_ready_payload(self) -> dict[str, Any]:
        return {
            "version": APP_VERSION,
            "protocol": PROTOCOL_VERSION,
            "provider": self.provider.provider_name,
            "preferred_model": self.provider.preferred_model,
            "context_window": self.provider.context_window,
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
            task.cancel()
            return

        await self.send_error(
            ws,
            "UNKNOWN_MESSAGE_TYPE",
            f"Unsupported message type: {message_type}",
            request_id=request_id,
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
                    str(error.get("code") or "OLLAMA_UNAVAILABLE"),
                    str(error.get("message") or "Ollama is unavailable."),
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
                f"Model is not installed in Ollama: {model}",
                request_id=request_id,
                thread_id=thread_id,
            )
            return False
        return True

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
        tools = project.tools
        state = project.state
        guard = ToolLoopGuard()

        history = trim_history(state.get_messages(thread_id))
        messages: list[dict[str, Any]] = [
            {
                "role": "system",
                "content": SYSTEM_PROMPT
                + "\n\nCurrent workspace: "
                + workspace.display_path,
            },
            *history,
            {"role": "user", "content": prompt},
        ]

        prompt_eval_count: int | None = None
        eval_count: int | None = None
        total_tool_calls = 0

        try:
            for step in range(1, self.MAX_MODEL_STEPS + 1):
                assistant_parts: list[str] = []
                tool_calls: list[ToolCall] = []
                step_tool_keys: set[str] = set()
                finish_reason: str | None = None
                observed_output = False

                for attempt in range(1, self.MODEL_RETRY_ATTEMPTS + 1):
                    try:
                        async for chunk in self.provider.stream_chat(
                            model=model,
                            messages=messages,
                            tools=tools.schemas(),
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
                    except OllamaProviderError as exc:
                        transient = exc.code in {
                            "OLLAMA_STREAM_FAILED",
                            "OLLAMA_UNAVAILABLE",
                        }
                        can_retry = (
                            transient
                            and not observed_output
                            and attempt < self.MODEL_RETRY_ATTEMPTS
                        )
                        if not can_retry:
                            raise

                        await ws.send_json(
                            envelope(
                                "turn.status",
                                {
                                    "phase": "model_retry",
                                    "message": (
                                        "Local model connection failed before producing output; "
                                        f"retrying ({attempt}/{self.MODEL_RETRY_ATTEMPTS - 1})."
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
                    if total_tool_calls > self.MAX_TOOL_CALLS:
                        await ws.send_json(
                            envelope(
                                "turn.failed",
                                {
                                    "code": "MAX_TOOL_CALLS",
                                    "message": (
                                        f"Agent exceeded {self.MAX_TOOL_CALLS} tool calls "
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
                            },
                            thread_id=thread_id,
                            turn_id=turn_id,
                        )
                    )

                    if not allowed:
                        payload: dict[str, Any] = {
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
                        async def on_output(
                            text: str,
                            *,
                            cid: str = call_id,
                            name: str = call.name,
                        ) -> None:
                            await ws.send_json(
                                envelope(
                                    "tool.output",
                                    {
                                        "tool_call_id": cid,
                                        "name": name,
                                        "output": text,
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
                            payload = result.to_dict()
                        except ToolError as exc:
                            payload = {
                                "ok": False,
                                "summary": exc.message,
                                "error": {
                                    "code": exc.code,
                                    "message": exc.message,
                                },
                                "changed_paths": [],
                            }
                        except Exception as exc:
                            payload = {
                                "ok": False,
                                "summary": f"Tool failed: {exc}",
                                "error": {
                                    "code": "TOOL_INTERNAL_ERROR",
                                    "message": str(exc),
                                },
                                "changed_paths": [],
                            }

                    guard.record_result(call.name, payload)

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

                    for changed_path in payload.get("changed_paths") or []:
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
                            "tool_name": call.name,
                            "content": json.dumps(
                                compact_tool_payload(payload),
                                ensure_ascii=False,
                            ),
                        }
                    )

                    if guard.blocked_repeats >= self.MAX_BLOCKED_REPEATS:
                        await ws.send_json(
                            envelope(
                                "turn.failed",
                                {
                                    "code": "TOOL_LOOP_DETECTED",
                                    "message": (
                                        "Agent repeatedly requested identical tool calls. "
                                        "The turn was stopped to prevent an unproductive loop."
                                    ),
                                    "recoverable": True,
                                    "provider": self.provider.provider_name,
                                    "model": model,
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

            await ws.send_json(
                envelope(
                    "turn.failed",
                    {
                        "code": "MAX_MODEL_STEPS",
                        "message": (
                            f"Agent exceeded {self.MAX_MODEL_STEPS} model steps "
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
        except OllamaProviderError as exc:
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
        for task in list(server.active_turns.values()):
            task.cancel()
        await runner.cleanup()
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
