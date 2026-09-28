from __future__ import annotations

import argparse
import json
import secrets
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from agent.core.version import APP_VERSION, PROTOCOL_VERSION


def build_health_payload(port: int) -> dict[str, Any]:
    return {
        "ok": True,
        "service": "local-coding-agent",
        "version": APP_VERSION,
        "protocol": PROTOCOL_VERSION,
        "port": port,
    }


def make_handler(token: str):
    class HealthHandler(BaseHTTPRequestHandler):
        server_version = "LocalCodingAgent/0.1"

        def _authorized(self) -> bool:
            return self.headers.get("Authorization") == f"Bearer {token}"

        def _send_json(self, status: int, payload: dict[str, Any]) -> None:
            body = json.dumps(payload).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:
            if self.path != "/health":
                self._send_json(404, {"ok": False, "error": "not_found"})
                return
            if not self._authorized():
                self._send_json(401, {"ok": False, "error": "unauthorized"})
                return

            port = int(self.server.server_address[1])
            self._send_json(200, build_health_payload(port))

        def do_POST(self) -> None:
            if self.path != "/shutdown":
                self._send_json(404, {"ok": False, "error": "not_found"})
                return
            if not self._authorized():
                self._send_json(401, {"ok": False, "error": "unauthorized"})
                return

            self._send_json(200, {"ok": True})
            threading.Thread(target=self.server.shutdown, daemon=True).start()

        def log_message(self, format: str, *args: object) -> None:
            print(f"[agent-http] {format % args}", flush=True)

    return HealthHandler


def run(host: str, port: int) -> None:
    token = secrets.token_urlsafe(24)
    server = ThreadingHTTPServer((host, port), make_handler(token))
    bound_port = int(server.server_address[1])

    ready = {
        "host": host,
        "port": bound_port,
        "token": token,
        "version": APP_VERSION,
        "protocol": PROTOCOL_VERSION,
    }
    print("LCA_AGENT_READY " + json.dumps(ready), flush=True)

    try:
        server.serve_forever(poll_interval=0.2)
    finally:
        server.server_close()
        print("LCA_AGENT_STOPPED", flush=True)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Local Coding Agent Phase 0 health server")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=0)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    run(args.host, args.port)


if __name__ == "__main__":
    main()
