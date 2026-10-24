"""M1: actual HTTP Provider, Task Runtime, files, Git and subprocesses.

Only model responses are scripted. Approval events are answered through the
real ApprovalManager as a test client; tool implementations are never patched.
"""
import asyncio
from dataclasses import replace
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from aiohttp import web

from agent.llm.router import validate_config
from agent.server.main import AgentServer


COMMAND = "uv run --no-project python -m unittest discover -s tests -v"
FIXTURE = Path(__file__).resolve().parents[1] / "manual-fixtures/v04-local-first"


def call(name, arguments, ident):
    return {"index": ident, "id": f"call_{ident}", "type": "function",
            "function": {"name": name, "arguments": json.dumps(arguments)}}


def tools(*calls):
    return {"delta": {"tool_calls": list(calls)}, "finish_reason": "tool_calls"}


def final(text="Real tool results reviewed", finish="stop"):
    return {"delta": {"content": text}, "finish_reason": finish}


class Client:
    def __init__(self, server):
        self.server, self.messages = server, []

    async def send_json(self, event):
        self.messages.append(event)
        if event["type"] == "approval.requested":
            self.server.approvals.respond(event["payload"]["approval_id"], "allow_once")


class SingleAgentTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.repo = self.root / "repo"
        shutil.copytree(FIXTURE, self.repo, ignore=shutil.ignore_patterns("__pycache__", ".venv"))
        for args in (["init", "-q", "-b", "main"], ["config", "user.name", "M1 test"],
                     ["config", "user.email", "m1@example.test"], ["add", "."], ["commit", "-qm", "fixture"]):
            subprocess.run(["git", *args], cwd=self.repo, check=True, capture_output=True)
        self.env = patch.dict(os.environ, {"LCA_DATA_DIR": str(self.root / "data"), "LCA_OPENAI_API_KEY": ""})
        self.env.start()
        self.server = AgentServer("test-session")
        self.server.permissions.set_mode("full_access")
        _, self.thread, _ = self.server.projects.open(str(self.repo), active_model="m1-model")
        self.client = Client(self.server)
        self.responses, self.requests, self.protocol_errors = [], [], []
        self.http_blocked = asyncio.Event()
        self.http_release = asyncio.Event()

        async def chat(request):
            body = await request.json()
            self.requests.append(body)
            # Strict gateway validation catches errors a permissive mock misses.
            pending = []
            for message in body["messages"]:
                if message.get("tool_calls"):
                    if pending:
                        self.protocol_errors.append("unanswered tool calls")
                    pending = [c["id"] for c in message["tool_calls"]]
                    for item in message["tool_calls"]:
                        if not isinstance(item["function"]["arguments"], str):
                            self.protocol_errors.append("arguments must be JSON strings")
                if message["role"] == "tool":
                    if message.get("tool_call_id") not in pending:
                        self.protocol_errors.append("orphan tool result")
                    else:
                        pending.remove(message["tool_call_id"])
                    if "tool_name" in message:
                        self.protocol_errors.append("internal tool_name leaked to wire")
            if pending:
                self.protocol_errors.append("missing tool results")
            if self.protocol_errors:
                return web.json_response({"error": "invalid tool protocol"}, status=400)
            if not self.responses:
                return web.json_response({"error": "unexpected model request"}, status=500)
            choice = self.responses.pop(0)
            if choice == "auth":
                return web.json_response({"error": "auth test"}, status=401)
            if choice == "block":
                self.http_blocked.set()
                await self.http_release.wait()
                choice = final()
            response = web.StreamResponse(headers={"Content-Type": "text/event-stream"})
            # Multiple network writes also exercise SSE reassembly.
            encoded = ("data: " + json.dumps({"choices": [choice], "usage": {
                "prompt_tokens": 100, "completion_tokens": 30}}) + "\n\ndata: [DONE]\n\n").encode()
            try:
                await response.prepare(request)
                for chunk in (encoded[:51], encoded[51:]):
                    await response.write(chunk)
                await response.write_eof()
            except ConnectionResetError:
                pass
            return response

        app = web.Application()
        app.router.add_post("/v1/chat/completions", chat)
        self.runner = web.AppRunner(app)
        await self.runner.setup()
        site = web.TCPSite(self.runner, "127.0.0.1", 0)
        await site.start()
        port = site._server.sockets[0].getsockname()[1]
        self.server.settings = replace(self.server.settings, openai_base_url=f"http://127.0.0.1:{port}/v1")
        self.config = validate_config({"strategy": "single-agent", "roles": {
            "executor": {"model": "m1-model", "context_window": 262144, "output_limit": 4096},
            # Deliberately broken bindings must not block the online Executor.
            "planner": {"model_profile_id": "missing-planner"},
            "reviewer": {"model_profile_id": "missing-reviewer"},
            "escalation": {"model_profile_id": "missing-escalation"}},
            "budget": {"api_calls": 30, "api_tokens": 3000000, "global_api_tokens": 9000000},
            "verification_commands": [COMMAND, "git diff --check"]})

    async def asyncTearDown(self):
        for running in list(self.server.active_turns.values()):
            running.cancel()
        await asyncio.gather(*list(self.server.active_turns.values()), return_exceptions=True)
        self.http_release.set()
        await self.runner.cleanup()
        await self.server.close_async()
        self.server.close()
        self.env.stop()
        self.temp.cleanup()

    async def start(self, responses, wait=True):
        self.responses = list(responses)
        # Update the existing global limits through the actual settings operation.
        await self.server.tasks.handle(self.client, {"type": "task.settings.update",
            "payload": {"config": self.config}}, set())
        await self.server.tasks.handle(self.client, {"type": "task.start", "thread_id": self.thread.id,
            "payload": {"goal": "Fix calculator and verify the actual tests", "config": self.config}}, set())
        running = list(self.server.active_turns.values())
        self.assertTrue(running, self.client.messages[-1])
        if wait:
            await asyncio.wait_for(asyncio.gather(*running), 45)
        return self.server.store.task_runtime.list(self.thread.id)[0]

    def fix(self):
        return tools(call("apply_patch", {"path": "calculator.py", "old_text": "return a - b", "new_text": "return a + b  # fixed"}, 5))

    def tool_results(self, name):
        return [e["payload"]["result"] for e in self.client.messages
                if e["type"] == "tool.completed" and e["payload"]["name"] == name]

    async def test_online_multiround_actual_failure_patch_retest_diff(self):
        task = await self.start([
            # Distinct IDs with identical arguments each need their own result.
            tools(call("read_file", {"path": "calculator.py"}, 0), call("read_file", {"path": "calculator.py"}, 1)),
            tools(call("run_command", {"command": COMMAND}, 2)), self.fix(),
            tools(call("run_command", {"command": COMMAND}, 6), call("git_diff", {}, 7)), final()])
        self.assertEqual(task["status"], "awaiting_approval", task["reason"])
        self.assertEqual(len(self.tool_results("read_file")), 2)
        commands = self.tool_results("run_command")
        self.assertNotEqual(commands[0]["exit_code"], 0)
        self.assertIn("FAILED", commands[0]["stderr"])
        self.assertEqual(commands[1]["exit_code"], 0)
        self.assertIn("a + b", Path(task["workspace"], "calculator.py").read_text())
        self.assertIn("a - b", (self.repo / "calculator.py").read_text())
        self.assertTrue(all(r["ok"] for r in task["verification"]))
        self.assertIn("a + b", task["report"]["diff"])
        self.assertEqual(task.get("planning_attempts", 0), 0)
        self.assertEqual(task["escalations"], 0)
        self.assertEqual(len(self.requests), 5)
        self.assertTrue(all(r["model"] == "m1-model" for r in self.requests))
        self.assertFalse(any(t["function"]["name"] == "submit_plan" for r in self.requests for t in r.get("tools", [])))
        self.assertFalse(self.protocol_errors)
        feedback = [json.loads(m["content"]) for m in self.requests[2]["messages"] if m["role"] == "tool"]
        self.assertTrue(any(r.get("exit_code") == 1 for r in feedback))
        calls = self.server.store.task_runtime.calls(task["id"])
        self.assertTrue(all(c["role"] == "executor" and c["route"] == "api" for c in calls))

    async def test_auth_error_pauses_with_no_planning_retry(self):
        task = await self.start(["auth"])
        self.assertEqual(task["status"], "paused")
        self.assertEqual(task["last_error"]["code"], "OPENAI_COMPATIBLE_AUTH_FAILED")
        self.assertEqual(len(self.requests), 1)
        report = self.server.tasks.diagnostics(task["id"])["diagnostics"]["json"]
        self.assertEqual(report["calls"][0]["metadata"]["http_status"], 401)

    async def test_independent_failure_returns_to_same_executor_for_repair(self):
        task = await self.start([tools(call("read_file", {"path": "calculator.py"}, 0)), final(), self.fix(), final()])
        self.assertEqual(task["status"], "awaiting_approval", task["reason"])
        self.assertEqual(task["repairs"], 1)
        self.assertEqual(task["escalations"], 0)
        self.assertEqual(len(self.requests), 4)
        self.assertIn("FAILED", str(self.requests[2]["messages"]))
        self.assertTrue(all(r["ok"] for r in task["verification"]))

    async def test_tool_error_is_fed_back_and_model_can_recover(self):
        task = await self.start([tools(call("read_file", {"path": "missing.py"}, 0)), self.fix(), final()])
        self.assertEqual(task["status"], "awaiting_approval", task["reason"])
        self.assertFalse(self.tool_results("read_file")[0]["ok"])
        feedback = [json.loads(m["content"]) for m in self.requests[1]["messages"] if m["role"] == "tool"]
        self.assertFalse(feedback[0]["ok"])
        self.assertTrue(feedback[0]["error"]["code"])

    async def test_request_timeout_is_diagnosed_without_retrying_planning(self):
        # Permit cold HTTP client setup; keep the request blocked and require
        # one actual request, a timeout, and no planning retry.
        self.config["budget"]["request_seconds"] = 3
        task = await self.start(["block"])
        self.assertEqual(task["status"], "paused")
        self.assertEqual(task["last_error"]["code"], "MODEL_TIMEOUT")
        self.assertEqual(len(self.requests), 1)

    async def test_malformed_tool_arguments_do_not_modify_files(self):
        bad = call("write_file", {}, 0)
        bad["function"]["arguments"] = '{"path": "calculator.py",'
        task = await self.start([tools(bad)])
        self.assertEqual(task["last_error"]["code"], "MODEL_INVALID_TOOL_CALL")
        self.assertFalse(self.tool_results("write_file"))
        self.assertIn("a - b", Path(task["workspace"], "calculator.py").read_text())
        self.assertEqual(len(self.requests), 1)

    async def test_truncated_response_is_not_completion(self):
        task = await self.start([final("Done", "length")])
        self.assertEqual(task["status"], "paused")
        self.assertEqual(task["last_error"]["code"], "MODEL_TRUNCATED")

    async def test_cancel_during_http_stops_task_and_retains_diagnostics(self):
        task = await self.start(["block"], wait=False)
        await asyncio.wait_for(self.http_blocked.wait(), 10)
        await self.server.tasks.handle(self.client, {"type": "task.cancel", "thread_id": self.thread.id,
            "payload": {"task_id": task["id"]}}, set())
        task = self.server.store.task_runtime.get(task["id"])
        self.assertEqual(task["status"], "cancelled")
        self.assertEqual(self.server.store.task_runtime.calls(task["id"])[0]["status"], "cancelled")
        self.assertFalse(self.server.active_turns)

    async def test_cancel_real_terminal_kills_delayed_write(self):
        command = ('uv run --no-project python -c "import time; from pathlib import Path; '
                   "Path('started.txt').write_text('started'); time.sleep(2); "
                   "Path('orphan.txt').write_text('bad'); time.sleep(30)\"")
        task = await self.start([tools(call("run_command", {"command": command}, 0))], wait=False)
        for _ in range(200):
            task = self.server.store.task_runtime.get(task["id"])
            if task["workspace"] and Path(task["workspace"], "started.txt").exists():
                break
            await asyncio.sleep(.05)
        else:
            self.fail("Real terminal process never started")
        await self.server.tasks.handle(self.client, {"type": "task.cancel", "thread_id": self.thread.id,
            "payload": {"task_id": task["id"]}}, set())
        await asyncio.sleep(2.2)
        self.assertFalse(Path(task["workspace"], "orphan.txt").exists())
        self.assertEqual(self.server.store.task_runtime.get(task["id"])["status"], "cancelled")
        self.assertEqual(len(self.requests), 1)

    async def test_no_progress_has_bounded_same_model_repairs(self):
        task = await self.start([tools(call("read_file", {"path": "calculator.py"}, 0)), final(),
                                 tools(call("read_file", {"path": "calculator.py"}, 1)), final()])
        self.assertEqual(task["status"], "paused", task["reason"])
        self.assertEqual(task["last_error"]["code"], "SINGLE_AGENT_NO_PROGRESS")
        self.assertEqual(len(self.requests), 4)
        self.assertTrue(any(not r["ok"] for r in task["verification"]))
        self.assertEqual(task["escalations"], 0)

    async def test_local_executor_binding_rejected_before_http(self):
        catalog = self.server.tasks.catalog().load()
        local = {"model_profile_id": "test-local", "connection_id": "legacy-ollama", "model_id": "offline-model", "display_name": "Offline"}
        catalog["profiles"].append(local)
        self.server.store.set_setting("models.catalog.v1", json.dumps(catalog))
        self.config["roles"]["executor"]["model_profile_id"] = local["model_profile_id"]
        task = await self.start([])
        self.assertEqual(task["status"], "paused")
        self.assertEqual(task["last_error"]["code"], "MODEL_POLICY_MISMATCH")
        self.assertFalse(self.requests)
