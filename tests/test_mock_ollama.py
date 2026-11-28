from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from urllib.request import urlopen, Request
from urllib.error import HTTPError


def _free_port():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class MockOllamaTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.port = _free_port()
        cls.proc = subprocess.Popen(
            [sys.executable, str(Path(__file__).parent / "mock_ollama_server.py"), "--port", str(cls.port)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        # Wait for server to start
        for _ in range(50):
            try:
                with urlopen(f"http://127.0.0.1:{cls.port}/api/tags", timeout=2) as r:
                    if r.status == 200:
                        break
            except Exception:
                time.sleep(0.2)
        else:
            raise RuntimeError("Mock server did not start")

    @classmethod
    def tearDownClass(cls):
        cls.proc.terminate()
        cls.proc.wait(timeout=5)

    def test_model_discovery(self):
        with urlopen(f"http://127.0.0.1:{self.port}/api/tags") as r:
            data = json.loads(r.read())
            self.assertIn("models", data)
            self.assertEqual(data["models"][0]["name"], "qwen3:4b")

    def test_chat_non_streaming(self):
        payload = json.dumps({
            "model": "qwen3:4b",
            "messages": [{"role": "user", "content": "Hello"}],
            "stream": False,
        }).encode()
        req = Request(f"http://127.0.0.1:{self.port}/api/chat", data=payload, headers={"Content-Type": "application/json"})
        with urlopen(req) as r:
            data = json.loads(r.read())
            self.assertIn("message", data)
            self.assertIn("Mock response", data["message"]["content"])

    def test_chat_streaming(self):
        payload = json.dumps({
            "model": "qwen3:4b",
            "messages": [{"role": "user", "content": "Hello"}],
            "stream": True,
        }).encode()
        req = Request(f"http://127.0.0.1:{self.port}/api/chat", data=payload, headers={"Content-Type": "application/json"})
        with urlopen(req) as r:
            lines = r.read().decode().strip().split("\n")
            self.assertGreater(len(lines), 1)
            # Last line should have done=True
            last = json.loads(lines[-1])
            self.assertTrue(last.get("done"))

    def test_tool_call_response(self):
        payload = json.dumps({
            "model": "qwen3:4b",
            "messages": [{"role": "user", "content": "Read file"}],
            "tools": [{"type": "function", "function": {"name": "read_file"}}],
            "stream": False,
        }).encode()
        req = Request(f"http://127.0.0.1:{self.port}/api/chat", data=payload, headers={"Content-Type": "application/json"})
        with urlopen(req) as r:
            data = json.loads(r.read())
            self.assertIn("tool_calls", data["message"])

    def test_error_401(self):
        payload = json.dumps({"model": "qwen3:4b", "messages": [{"role": "user", "content": "Hi"}], "stream": False}).encode()
        req = Request(f"http://127.0.0.1:{self.port}/api/chat?error=401", data=payload, headers={"Content-Type": "application/json"})
        with self.assertRaises(HTTPError) as ctx:
            urlopen(req)
        self.assertEqual(ctx.exception.code, 401)

    def test_error_429(self):
        payload = json.dumps({"model": "qwen3:4b", "messages": [{"role": "user", "content": "Hi"}], "stream": False}).encode()
        req = Request(f"http://127.0.0.1:{self.port}/api/chat?error=429", data=payload, headers={"Content-Type": "application/json"})
        with self.assertRaises(HTTPError) as ctx:
            urlopen(req)
        self.assertEqual(ctx.exception.code, 429)

    def test_error_500(self):
        payload = json.dumps({"model": "qwen3:4b", "messages": [{"role": "user", "content": "Hi"}], "stream": False}).encode()
        req = Request(f"http://127.0.0.1:{self.port}/api/chat?error=500", data=payload, headers={"Content-Type": "application/json"})
        with self.assertRaises(HTTPError) as ctx:
            urlopen(req)
        self.assertEqual(ctx.exception.code, 500)

    def test_quota_exhausted(self):
        payload = json.dumps({"model": "qwen3:4b", "messages": [{"role": "user", "content": "Hi"}], "stream": False}).encode()
        req = Request(f"http://127.0.0.1:{self.port}/api/chat?error=quota_exhausted", data=payload, headers={"Content-Type": "application/json"})
        with self.assertRaises(HTTPError) as ctx:
            urlopen(req)
        self.assertEqual(ctx.exception.code, 429)


if __name__ == "__main__":
    unittest.main()
