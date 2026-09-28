from __future__ import annotations

import argparse
import asyncio
import json
import secrets
from contextlib import suppress
from typing import Any

from aiohttp import WSMsgType, web

from agent.core.version import APP_VERSION, PROTOCOL_VERSION
from agent.server.protocol import envelope, new_id, validate_client_message
from agent.server.state import InMemoryState


def build_health_payload(port: int) -> dict[str, Any]:
    return {
        "ok": True,
        "service": "local-coding-agent",
        "version": APP_VERSION,
        "protocol": PROTOCOL_VERSION,
        "port": port,
    }


class AgentServer:
    def __init__(self, token: str) -> None:
        self.token = token
        self.state = InMemoryState()
        self.active_turns: dict[str, asyncio.Task[None]] = {}

    def authorized(self, request: web.Request) -> bool:
        return request.headers.get("Authorization") == f"Bearer {self.token}"

    async def health(self, request: web.Request) -> web.Response:
        if not self.authorized(request):
            return web.json_response({"ok": False, "error": "unauthorized"}, status=401)
        port = int(request.transport.get_extra_info("sockname")[1])
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
                {
                    "version": APP_VERSION,
                    "protocol": PROTOCOL_VERSION,
                },
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
                envelope(
                    "server.ready",
                    {
                        "version": APP_VERSION,
                        "protocol": PROTOCOL_VERSION,
                    },
                    request_id=request_id,
                )
            )
            return

        if message_type == "thread.create":
            thread = self.state.create_thread(payload.get("title"))
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
                await self.send_error(
                    ws,
                    "THREAD_NOT_FOUND",
                    "Thread does not exist.",
                    request_id=request_id,
                    thread_id=thread_id or None,
                )
                return
            await ws.send_json(
                envelope(
                    "thread.loaded",
                    {"thread": thread.to_dict()},
                    request_id=request_id,
                    thread_id=thread.id,
                )
            )
            return

        if message_type == "turn.start":
            thread_id = str(data.get("thread_id") or payload.get("thread_id") or "")
            prompt = str(payload.get("prompt") or "").strip()
            thread = self.state.get_thread(thread_id)

            if not thread:
                await self.send_error(
                    ws,
                    "THREAD_NOT_FOUND",
                    "Create or load a thread before starting a turn.",
                    request_id=request_id,
                    thread_id=thread_id or None,
                )
                return
            if not prompt:
                await self.send_error(
                    ws,
                    "EMPTY_PROMPT",
                    "Prompt cannot be empty.",
                    request_id=request_id,
                    thread_id=thread_id,
                )
                return

            turn_id = new_id("turn")
            self.state.touch_thread(thread_id)
            await ws.send_json(
                envelope(
                    "turn.started",
                    {"prompt": prompt},
                    request_id=request_id,
                    thread_id=thread_id,
                    turn_id=turn_id,
                )
            )

            task = asyncio.create_task(
                self.simulate_turn(ws, thread_id, turn_id, prompt),
                name=turn_id,
            )
            self.active_turns[turn_id] = task
            owned_turns.add(turn_id)
            task.add_done_callback(
                lambda _task, tid=turn_id: self.active_turns.pop(tid, None)
            )
            return

        if message_type == "turn.cancel":
            turn_id = str(data.get("turn_id") or payload.get("turn_id") or "")
            task = self.active_turns.get(turn_id)
            if not task or task.done():
                await self.send_error(
                    ws,
                    "TURN_NOT_RUNNING",
                    "Turn is not running.",
                    request_id=request_id,
                    turn_id=turn_id or None,
                )
                return
            task.cancel()
            return

        await self.send_error(
            ws,
            "UNKNOWN_MESSAGE_TYPE",
            f"Unsupported message type: {message_type}",
            request_id=request_id,
        )

    async def simulate_turn(
        self,
        ws: web.WebSocketResponse,
        thread_id: str,
        turn_id: str,
        prompt: str,
    ) -> None:
        text = (
            "Phase 1 protocol is working. "
            f"I received your task: {prompt} "
            "This response is simulated; Ollama is connected in Phase 2."
        )

        try:
            for start in range(0, len(text), 12):
                await asyncio.sleep(0.08)
                await ws.send_json(
                    envelope(
                        "turn.delta",
                        {"delta": text[start : start + 12]},
                        thread_id=thread_id,
                        turn_id=turn_id,
                    )
                )

            await ws.send_json(
                envelope(
                    "turn.completed",
                    {"finish_reason": "stop"},
                    thread_id=thread_id,
                    turn_id=turn_id,
                )
            )
        except asyncio.CancelledError:
            with suppress(ConnectionResetError, RuntimeError):
                await ws.send_json(
                    envelope(
                        "turn.cancelled",
                        {"reason": "user_cancelled"},
                        thread_id=thread_id,
                        turn_id=turn_id,
                    )
                )
            raise
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
