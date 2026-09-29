from __future__ import annotations

import argparse
import asyncio
import json
import secrets
from contextlib import suppress
from typing import Any

from aiohttp import WSMsgType, web

from agent.core.version import APP_VERSION, PROTOCOL_VERSION
from agent.llm.base import ToolCall
from agent.llm.ollama import OllamaProvider, OllamaProviderError
from agent.server.protocol import envelope, new_id, validate_client_message
from agent.server.state import InMemoryState
from agent.tools.base import ToolError
from agent.tools.registry import ToolRegistry
from agent.tools.workspace import Workspace


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

Phase 3 blocks destructive commands such as bulk deletion, git reset --hard, git clean and git push.
Do not try to bypass those restrictions.
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
    MAX_TOOL_STEPS = 12

    def __init__(self, token: str) -> None:
        self.token = token
        self.state = InMemoryState()
        self.provider = OllamaProvider()
        self.active_turns: dict[str, asyncio.Task[None]] = {}
        self.available_models: set[str] = set()
        self.default_model: str | None = self.provider.preferred_model
        self.workspace: Workspace | None = None
        self.tools: ToolRegistry | None = None

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
            "workspace": self.workspace.display_path if self.workspace else None,
            "tools": self.tools.names if self.tools else [],
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
                workspace = Workspace(raw_path)
            except (ToolError, OSError) as exc:
                message = exc.message if isinstance(exc, ToolError) else str(exc)
                await self.send_error(
                    ws,
                    "WORKSPACE_OPEN_FAILED",
                    message,
                    request_id=request_id,
                )
                return

            self.workspace = workspace
            self.tools = ToolRegistry(workspace)
            self.state = InMemoryState()
            await ws.send_json(
                envelope(
                    "project.opened",
                    {
                        "path": workspace.display_path,
                        "name": workspace.root.name,
                        "tools": self.tools.names,
                    },
                    request_id=request_id,
                )
            )
            return

        if message_type == "project.get":
            await ws.send_json(
                envelope(
                    "project.loaded",
                    {
                        "path": self.workspace.display_path if self.workspace else None,
                        "name": self.workspace.root.name if self.workspace else None,
                        "tools": self.tools.names if self.tools else [],
                    },
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
            thread = self.state.get_thread(thread_id)
            if not thread:
                await self.send_error(ws, "THREAD_NOT_FOUND", "Thread does not exist.", request_id=request_id, thread_id=thread_id or None)
                return
            if not model:
                await self.send_error(ws, "MODEL_REQUIRED", "Model name cannot be empty.", request_id=request_id, thread_id=thread_id)
                return
            if not await self.ensure_model_available(ws, model, request_id=request_id, thread_id=thread_id):
                return
            updated = self.state.set_thread_model(thread_id, model)
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
            if not self.workspace:
                await self.send_error(
                    ws,
                    "WORKSPACE_REQUIRED",
                    "Open a project before creating a coding thread.",
                    request_id=request_id,
                )
                return
            requested_model = str(payload.get("model") or "").strip() or None
            thread = self.state.create_thread(
                payload.get("title"),
                active_model=requested_model or self.default_model,
            )
            await ws.send_json(
                envelope(
                    "thread.created",
                    {"thread": thread.to_dict()},
                    request_id=request_id,
                    thread_id=thread.id,
                )
            )
            return

        if message_type == "thread.list":
            await ws.send_json(
                envelope(
                    "thread.listed",
                    {"threads": [item.to_dict() for item in self.state.list_threads()]},
                    request_id=request_id,
                )
            )
            return

        if message_type == "thread.get":
            thread_id = str(payload.get("thread_id") or data.get("thread_id") or "")
            thread = self.state.get_thread(thread_id)
            if not thread:
                await self.send_error(ws, "THREAD_NOT_FOUND", "Thread does not exist.", request_id=request_id, thread_id=thread_id or None)
                return
            await ws.send_json(
                envelope(
                    "thread.loaded",
                    {
                        "thread": thread.to_dict(),
                        "messages": self.state.get_messages(thread.id),
                    },
                    request_id=request_id,
                    thread_id=thread.id,
                )
            )
            return

        if message_type == "turn.start":
            thread_id = str(data.get("thread_id") or payload.get("thread_id") or "")
            prompt = str(payload.get("prompt") or "").strip()
            thread = self.state.get_thread(thread_id)

            if not self.workspace or not self.tools:
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
            self.state.touch_thread(thread_id)
            await ws.send_json(
                envelope(
                    "turn.started",
                    {
                        "prompt": prompt,
                        "model": model,
                        "provider": self.provider.provider_name,
                        "workspace": self.workspace.display_path,
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
        assert self.workspace is not None
        assert self.tools is not None

        history = self.state.get_messages(thread_id)
        messages: list[dict[str, Any]] = [
            {
                "role": "system",
                "content": SYSTEM_PROMPT
                + "\n\nCurrent workspace: "
                + self.workspace.display_path,
            },
            *history,
            {"role": "user", "content": prompt},
        ]
        final_parts: list[str] = []
        prompt_eval_count: int | None = None
        eval_count: int | None = None

        try:
            for step in range(1, self.MAX_TOOL_STEPS + 1):
                assistant_parts: list[str] = []
                tool_calls: list[ToolCall] = []
                finish_reason: str | None = None

                async for chunk in self.provider.stream_chat(
                    model=model,
                    messages=messages,
                    tools=self.tools.schemas(),
                ):
                    if chunk.content:
                        assistant_parts.append(chunk.content)
                        final_parts.append(chunk.content)
                        await ws.send_json(
                            envelope(
                                "turn.delta",
                                {"delta": chunk.content},
                                thread_id=thread_id,
                                turn_id=turn_id,
                            )
                        )
                    if chunk.tool_calls:
                        tool_calls.extend(chunk.tool_calls)
                    if chunk.done:
                        finish_reason = chunk.finish_reason
                        prompt_eval_count = chunk.prompt_eval_count
                        eval_count = chunk.eval_count

                assistant_text = "".join(assistant_parts)
                if not tool_calls:
                    final_text = "".join(final_parts)
                    self.state.append_exchange(
                        thread_id,
                        user=prompt,
                        assistant=final_text,
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
                                "tool_steps": step - 1,
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
                    call_id = f"{turn_id}:{step}:{call_index}"
                    await ws.send_json(
                        envelope(
                            "tool.requested",
                            {
                                "tool_call_id": call_id,
                                "name": call.name,
                                "arguments": call.arguments,
                            },
                            thread_id=thread_id,
                            turn_id=turn_id,
                        )
                    )
                    await ws.send_json(
                        envelope(
                            "tool.started",
                            {"tool_call_id": call_id, "name": call.name},
                            thread_id=thread_id,
                            turn_id=turn_id,
                        )
                    )

                    async def on_output(text: str, *, cid: str = call_id, name: str = call.name) -> None:
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
                        result = await self.tools.execute(
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
                        }
                    except Exception as exc:
                        payload = {
                            "ok": False,
                            "summary": f"Tool failed: {exc}",
                            "error": {
                                "code": "TOOL_INTERNAL_ERROR",
                                "message": str(exc),
                            },
                        }

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
                                {"path": changed_path, "tool_call_id": call_id},
                                thread_id=thread_id,
                                turn_id=turn_id,
                            )
                        )

                    messages.append(
                        {
                            "role": "tool",
                            "tool_name": call.name,
                            "content": json.dumps(payload, ensure_ascii=False),
                        }
                    )

            await ws.send_json(
                envelope(
                    "turn.failed",
                    {
                        "code": "MAX_TOOL_STEPS",
                        "message": f"Agent exceeded {self.MAX_TOOL_STEPS} tool steps.",
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
