"""Mock Ollama HTTP server for automated testing.

Simulates Ollama API endpoints:
- GET /api/tags (model list)
- POST /api/chat (chat completion, streaming)
- POST /api/generate (text generation)

Supports configurable error injection via query params or headers.
"""
from __future__ import annotations

import json
import time
from http.server import HTTPServer, BaseHTTPRequestHandler
from typing import Any
from urllib.parse import urlparse, parse_qs


class MockOllamaHandler(BaseHTTPRequestHandler):
    """HTTP handler for mock Ollama API."""

    # Class-level configuration
    error_mode: str | None = None  # "401", "403", "429", "500", "timeout", "disconnect", "quota_exhausted"
    delay_seconds: float = 0.0
    stream: bool = True

    def log_message(self, format, *args):
        pass  # Suppress logs

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == "/api/tags":
            self._handle_tags()
        else:
            self.send_error(404, "Not Found")

    def do_POST(self):
        parsed = urlparse(self.path)
        if parsed.path == "/api/chat":
            self._handle_chat(parsed)
        elif parsed.path == "/api/generate":
            self._handle_generate(parsed)
        else:
            self.send_error(404, "Not Found")

    def _handle_tags(self):
        models = {
            "models": [
                {
                    "name": "qwen3:4b",
                    "model": "qwen3:4b",
                    "modified_at": "2026-11-28T00:00:00Z",
                    "size": 2497293931,
                    "digest": "abc123",
                    "details": {
                        "parent_model": "",
                        "format": "gguf",
                        "family": "qwen3",
                        "families": ["qwen3"],
                        "parameter_size": "4.0B",
                        "quantization_level": "Q4_K_M",
                    },
                }
            ]
        }
        self._send_json(200, models)

    def _handle_chat(self, parsed):
        params = parse_qs(parsed.query)
        error_mode = params.get("error", [self.error_mode])[0] if params.get("error") else self.error_mode

        if error_mode:
            self._handle_error(error_mode)
            return

        if self.delay_seconds > 0:
            time.sleep(self.delay_seconds)

        content_length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_length) if content_length > 0 else b"{}"
        try:
            request = json.loads(body)
        except json.JSONDecodeError:
            request = {}

        messages = request.get("messages", [])
        stream = request.get("stream", True)
        model = request.get("model", "qwen3:4b")

        # Generate response based on last user message
        last_user = ""
        for m in reversed(messages):
            if m.get("role") == "user":
                last_user = m.get("content", "")
                break

        response_text = f"Mock response to: {last_user[:50]}"

        # Check if tool call requested
        tools = request.get("tools", [])
        if tools and "read_file" in str(tools):
            # Simulate tool call response
            if stream:
                self._stream_tool_call(response_text, model)
            else:
                self._send_json(200, {
                    "model": model,
                    "created_at": "2026-11-28T00:00:00Z",
                    "message": {
                        "role": "assistant",
                        "content": "",
                        "tool_calls": [
                            {
                                "function": {
                                    "name": "read_file",
                                    "arguments": {"path": "value.py"},
                                }
                            }
                        ],
                    },
                    "done": True,
                })
            return

        if stream:
            self._stream_response(response_text, model)
        else:
            self._send_json(200, {
                "model": model,
                "created_at": "2026-11-28T00:00:00Z",
                "message": {"role": "assistant", "content": response_text},
                "done": True,
                "total_duration": 1000000,
                "load_duration": 100000,
                "prompt_eval_count": 10,
                "eval_count": 20,
            })

    def _handle_generate(self, parsed):
        self._send_json(200, {
            "model": "qwen3:4b",
            "created_at": "2026-11-28T00:00:00Z",
            "response": "Mock generated text",
            "done": True,
        })

    def _stream_response(self, text, model):
        self.send_response(200)
        self.send_header("Content-Type", "application/x-ndjson")
        self.end_headers()

        # Stream word by word
        words = text.split()
        for word in words:
            chunk = {
                "model": model,
                "created_at": "2026-11-28T00:00:00Z",
                "message": {"role": "assistant", "content": word + " "},
                "done": False,
            }
            self.wfile.write((json.dumps(chunk) + "\n").encode())
            self.wfile.flush()
            time.sleep(0.01)

        # Final chunk
        final = {
            "model": model,
            "created_at": "2026-11-28T00:00:00Z",
            "message": {"role": "assistant", "content": ""},
            "done": True,
            "total_duration": 1000000,
            "prompt_eval_count": 10,
            "eval_count": len(words),
        }
        self.wfile.write((json.dumps(final) + "\n").encode())
        self.wfile.flush()

    def _stream_tool_call(self, text, model):
        self.send_response(200)
        self.send_header("Content-Type", "application/x-ndjson")
        self.send_header("Transfer-Encoding", "chunked")
        self.end_headers()

        chunk = {
            "model": model,
            "created_at": "2026-11-28T00:00:00Z",
            "message": {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {
                        "function": {
                            "name": "read_file",
                            "arguments": {"path": "value.py"},
                        }
                    }
                ],
            },
            "done": False,
        }
        self.wfile.write((json.dumps(chunk) + "\n").encode())
        self.wfile.flush()

        final = {
            "model": model,
            "created_at": "2026-11-28T00:00:00Z",
            "message": {"role": "assistant", "content": ""},
            "done": True,
            "total_duration": 1000000,
            "prompt_eval_count": 10,
            "eval_count": 5,
        }
        self.wfile.write((json.dumps(final) + "\n").encode())
        self.wfile.flush()

    def _handle_error(self, error_mode):
        if error_mode == "401":
            self._send_json(401, {"error": "Unauthorized"})
        elif error_mode == "403":
            self._send_json(403, {"error": "Forbidden"})
        elif error_mode == "429":
            self._send_json(429, {"error": "Rate limit exceeded"})
        elif error_mode == "500":
            self._send_json(500, {"error": "Internal server error"})
        elif error_mode == "timeout":
            time.sleep(30)  # Simulate timeout
            self._send_json(200, {"error": "timeout"})
        elif error_mode == "disconnect":
            self.close_connection = True
        elif error_mode == "quota_exhausted":
            self._send_json(429, {"error": "quota exhausted", "usage": {"total_tokens": 1000000}})

    def _send_json(self, status, data):
        body = json.dumps(data).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)
        self.wfile.flush()


def run_server(port=11434, error_mode=None):
    """Start the mock server on the given port."""
    MockOllamaHandler.error_mode = error_mode
    server = HTTPServer(("127.0.0.1", port), MockOllamaHandler)
    print(f"Mock Ollama server running on port {port}")
    server.serve_forever()


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=11434)
    parser.add_argument("--error", type=str, default=None)
    args = parser.parse_args()
    run_server(args.port, args.error)
