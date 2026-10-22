"""Mock models, real existing Agent Loop/tools, isolated Git worktrees and tests."""
import asyncio
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from agent.core.budget import BudgetExceeded, BudgetGuard
from agent.core.verification import classify, discover_commands
from agent.llm.base import ProviderError, ProviderChunk
from agent.llm.router import ModelRouter, validate_config
from agent.server.main import AgentServer
from test_agent_reliability import FakeWebSocket, ScriptedProvider, final_step, tool_step

PLAN = final_step(json.dumps({"steps": [{"description": "Inspect and fix calculator using actual tools"}]}))
COMMAND = "uv run --no-project python -m unittest discover -s tests -v"


class TaskTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.repo = self.root / "repo"
        self.repo.mkdir()
        self.env = patch.dict(os.environ, {"LCA_DATA_DIR": str(self.root / "data")})
        self.env.start()
        (self.repo / "calculator.py").write_text("def add(a, b):\n    return a - b\n", encoding="utf-8")
        (self.repo / ".gitignore").write_text("__pycache__/\n.venv/\n", encoding="utf-8")
        (self.repo / "tests").mkdir()
        (self.repo / "tests/test_calc.py").write_text("import unittest\nfrom calculator import add\nclass Calc(unittest.TestCase):\n def test_add(self): self.assertEqual(add(3, 2), 5)\n", encoding="utf-8")
        for args in (["init", "-q", "-b", "main"], ["config", "user.name", "Test"], ["config", "user.email", "test@example.test"], ["add", "."], ["commit", "-qm", "fixture"]):
            subprocess.run(["git", *args], cwd=self.repo, check=True, capture_output=True)
        self.server = AgentServer("test")
        self.project, self.thread, _ = self.server.projects.open(str(self.repo), active_model="test")
        self.ws = FakeWebSocket()
        async def approve(*args, **kwargs):
            return "allow_once"
        self.server.approvals.request = approve

    async def asyncTearDown(self):
        for running in list(self.server.active_turns.values()):
            running.cancel()
        await asyncio.gather(*self.server.active_turns.values(), return_exceptions=True)
        await self.server.close_async()
        self.server.close()
        self.env.stop()
        self.temp.cleanup()

    def config(self, **budget):
        return validate_config({"roles": {role: {"model": role, "context_window": 65536} for role in ("planner", "executor", "reviewer", "escalation")},
                                "budget": budget, "verification_commands": [COMMAND, "git diff --check"]})

    async def run_task(self, local_steps, api_steps=None, config=None):
        local, api = ScriptedProvider(local_steps), ScriptedProvider(api_steps or [])
        self.server.tasks.provider_factory_override = lambda route, profile: local if route == "local" else api
        await self.server.tasks.handle(self.ws, {"type": "task.start", "thread_id": self.thread.id,
            "payload": {"goal": "Fix calculator addition", "config": config or self.config()}}, set())
        tasks = list(self.server.active_turns.values())
        self.assertTrue(tasks, self.ws.messages[-1])
        await asyncio.wait_for(asyncio.gather(*tasks), 30)
        task = self.server.store.task_runtime.list(self.thread.id)[0]
        return task, local, api

    def fix(self):
        return tool_step("apply_patch", {"path": "calculator.py", "old_text": "return a - b", "new_text": "return a + b"})

    async def test_local_success_no_api_real_tests_and_source_unchanged(self):
        (self.repo / "user-untracked.txt").write_text("preserve")
        task, local, api = await self.run_task([PLAN, self.fix(), final_step(), final_step("No additional risks")])
        self.assertEqual(task["status"], "awaiting_approval", task["reason"])
        self.assertEqual(api.calls, 0)
        self.assertEqual(self.server.store.task_runtime.usage(task["id"])["api_calls"], 0)
        self.assertTrue(all(r["ok"] for r in task["verification"]))
        self.assertIn("a - b", (self.repo / "calculator.py").read_text())
        self.assertEqual((self.repo / "user-untracked.txt").read_text(), "preserve")
        self.assertIn("a + b", Path(task["workspace"], "calculator.py").read_text())
        self.assertEqual(subprocess.check_output(["git", "rev-list", "--count", "HEAD"], cwd=task["workspace"], text=True).strip(), "1")
        self.assertTrue(Path(task["verification"][0]["log_path"]).stat().st_size)
        await self.server.tasks.handle(self.ws, {"type": "task.approve", "thread_id": self.thread.id, "payload": {"task_id": task["id"]}}, set())
        self.assertEqual(self.server.store.task_runtime.get(task["id"])["status"], "completed")

    async def test_failure_escalation_advice_returns_to_local(self):
        # First real edit is wrong, independent unittest fails; diagnosis has no tools.
        wrong = tool_step("apply_patch", {"path": "calculator.py", "old_text": "a - b", "new_text": "a * b"})
        corrected = tool_step("apply_patch", {"path": "calculator.py", "old_text": "a * b", "new_text": "a + b"})
        task, local, api = await self.run_task([PLAN, wrong, final_step(), corrected, final_step(), final_step("Reviewed")],
                                              [final_step("Replace multiplication with addition")], self.config(local_repairs=0))
        self.assertEqual(task["status"], "awaiting_approval", task["reason"])
        self.assertEqual(task["escalations"], 1)
        self.assertEqual(api.calls, 1)
        self.assertEqual(task["attempts"], 2)
        self.assertGreater(local.calls, api.calls)

    async def test_zero_api_calls_and_token_insufficiency_never_send(self):
        for limits in ({"api_calls": 0}, {"api_tokens": 1}):
            with self.subTest(limits=limits):
                task, local, api = await self.run_task([PLAN, tool_step("read_file", {"path": "calculator.py"}), final_step()],
                    [final_step("must not be sent")], self.config(local_repairs=0, **limits))
                self.assertEqual(api.calls, 0)
                self.assertEqual(task["status"], "paused", task["reason"])
                self.assertFalse(task["report"].get("passed"))

    async def test_repeated_failure_loop_triggers_bounded_escalation(self):
        read = tool_step("read_file", {"path": "calculator.py"})
        task, local, api = await self.run_task([PLAN, read, final_step(), read, final_step(), self.fix(), final_step(), final_step("review")],
                                              [final_step("Use addition")])
        self.assertEqual(task["status"], "awaiting_approval", task["reason"])
        self.assertEqual(task["escalations"], 1)

    async def test_ollama_unavailable_pauses_without_api(self):
        class Offline(ScriptedProvider):
            async def stream_chat(self, **kwargs):
                raise ProviderError("OLLAMA_UNAVAILABLE", "Ollama is offline")
                yield
        offline, api = Offline([]), ScriptedProvider([])
        self.server.tasks.provider_factory_override = lambda route, _: offline if route == "local" else api
        await self.server.tasks.handle(self.ws, {"type": "task.start", "thread_id": self.thread.id,
            "payload": {"goal": "Fix calculator", "config": self.config()}}, set())
        await asyncio.gather(*list(self.server.active_turns.values()))
        task = self.server.store.task_runtime.list(self.thread.id)[0]
        self.assertEqual(task["status"], "paused")
        self.assertEqual(api.calls, 0)

    async def test_api_errors_are_charged_and_not_retried_unbounded(self):
        for code in ("MODEL_TIMEOUT", "OPENAI_COMPATIBLE_RATE_LIMITED", "OPENAI_COMPATIBLE_STREAM_FAILED"):
            with self.subTest(code=code):
                class Broken(ScriptedProvider):
                    async def stream_chat(self, **kwargs):
                        self.calls += 1
                        raise ProviderError(code, "Network error")
                        yield
                api = Broken([])
                local = ScriptedProvider([PLAN, tool_step("read_file", {"path": "calculator.py"}), final_step()])
                self.server.tasks.provider_factory_override = lambda route, _: local if route == "local" else api
                await self.server.tasks.handle(self.ws, {"type": "task.start", "thread_id": self.thread.id,
                    "payload": {"goal": "Fix calculator", "config": self.config(local_repairs=0)}}, set())
                await asyncio.gather(*list(self.server.active_turns.values()))
                task = self.server.store.task_runtime.list(self.thread.id)[0]
                self.assertEqual(task["status"], "paused", task["reason"])
                self.assertEqual(api.calls, 1)
                self.assertEqual(self.server.store.task_runtime.usage(task["id"])["api_calls"], 1)

    async def test_budget_survives_restart_and_illegal_transitions_rejected(self):
        runtime = self.server.store.task_runtime
        task = runtime.create(self.thread.id, "budget", self.config(api_calls=1), str(self.repo))
        guard = BudgetGuard(runtime, task["id"], self.config()["budget"])
        kwargs = dict(route="api", role="escalation", model="test", messages=[{"role": "user", "content": "hi"}], tools=None, context_window=4096, output_limit=100)
        request = guard.reserve(**kwargs)
        before = runtime.usage(task["id"])
        with self.assertRaises(BudgetExceeded): guard.reserve(**kwargs)
        with self.assertRaises(ValueError): runtime.transition(task["id"], "completed")
        runtime.transition(task["id"], "planning")
        await self.server.close_async()
        self.server.close()
        self.server = AgentServer("restart")
        runtime = self.server.store.task_runtime
        self.assertEqual(runtime.get(task["id"])["status"], "paused")
        self.assertEqual(runtime.usage(task["id"]), before)
        guard = BudgetGuard(runtime, task["id"], self.config()["budget"])
        with self.assertRaises(BudgetExceeded): guard.reserve(**kwargs)
        guard.finish(request, "completed", {"input_tokens": 1, "output_tokens": 2, "estimated": False})
        guard.finish(request, "completed", {"input_tokens": 10000})
        self.assertEqual(runtime.usage(task["id"])["input_tokens"], 1)

    async def test_read_only_and_git_approval_are_not_bypassed(self):
        self.server.permissions.set_mode("read_only")
        task, local, api = await self.run_task([PLAN])
        self.assertEqual(task["status"], "paused")
        self.assertEqual(local.calls, 0)
        self.assertEqual(subprocess.check_output(["git", "status", "--porcelain"], cwd=self.repo, text=True), "")

    async def test_pause_verification_kills_real_descendant_and_retains_checkpoint(self):
        (self.repo / "sleepy.py").write_text(
            "import subprocess,sys,time\nsubprocess.Popen([sys.executable,'-c',\"import time; time.sleep(3); open('orphan.txt','w').write('bad')\"])\nprint('TASK_READY',flush=True)\ntime.sleep(60)\n", encoding="utf-8")
        subprocess.run(["git", "add", "sleepy.py"], cwd=self.repo, check=True, capture_output=True)
        subprocess.run(["git", "commit", "-qm", "sleep fixture"], cwd=self.repo, check=True, capture_output=True)
        config = self.config()
        config["verification_commands"] = ["uv run --no-project python sleepy.py"]
        local = ScriptedProvider([PLAN, self.fix(), final_step()])
        self.server.tasks.provider_factory_override = lambda *_: local
        await self.server.tasks.handle(self.ws, {"type":"task.start", "thread_id":self.thread.id,
            "payload":{"goal":"Fix calculator", "config":config}}, set())
        for _ in range(200):
            if any(e["type"] == "tool.output" and "TASK_READY" in str(e["payload"].get("text", "")) for e in self.ws.messages): break
            await asyncio.sleep(.05)
        else: self.fail("Verification process did not start")
        task = self.server.store.task_runtime.list(self.thread.id)[0]
        await self.server.tasks.handle(self.ws, {"type":"task.pause", "thread_id":self.thread.id, "payload":{"task_id":task["id"]}}, set())
        await asyncio.sleep(3.2)
        self.assertFalse(Path(task["workspace"], "orphan.txt").exists())
        self.assertEqual(self.server.store.task_runtime.get(task["id"])["status"], "paused")
        self.assertEqual(self.server.store.task_plans.latest_checkpoint(task["id"])["reason"], "task_paused")

    async def test_acceptance_rejects_new_untracked_file_after_verification(self):
        task, _, _ = await self.run_task([PLAN, self.fix(), final_step(), final_step("review")])
        self.assertEqual(task["status"], "awaiting_approval", task["reason"])
        Path(task["workspace"], "unreviewed.py").write_text("print('new untested code')")
        await self.server.tasks.handle(self.ws, {"type":"task.approve", "thread_id":self.thread.id, "payload":{"task_id":task["id"]}}, set())
        self.assertEqual(self.ws.messages[-1]["type"], "error")
        self.assertEqual(self.server.store.task_runtime.get(task["id"])["status"], "awaiting_approval")

    async def test_global_budget_and_cost_caps_precheck(self):
        runtime = self.server.store.task_runtime
        config = self.config()
        task = runtime.create(self.thread.id, "budget", config, str(self.repo))
        guard = BudgetGuard(runtime, task["id"], {**config["budget"], "global_api_calls":0})
        kwargs = dict(route="api", role="escalation", model="test", messages=[], tools=None, context_window=4096, output_limit=100)
        with self.assertRaises(BudgetExceeded): guard.reserve(**kwargs)
        task["config"]["budget"]["api_cost"] = .001
        runtime.save(task)
        guard = BudgetGuard(runtime, task["id"], config["budget"])
        with self.assertRaises(BudgetExceeded): guard.reserve(**kwargs)
        with self.assertRaises(BudgetExceeded): guard.reserve(**kwargs, input_price=1000, output_price=1000)
        self.assertEqual(runtime.usage(task["id"])["api_calls"], 0)

    async def test_cancelled_task_resume_does_not_replay_completed_mutation(self):
        task, _, _ = await self.run_task([PLAN, self.fix(), final_step(), final_step("review")])
        await self.server.tasks.handle(self.ws, {"type":"task.cancel", "thread_id":self.thread.id, "payload":{"task_id":task["id"]}}, set())
        original_count = self.server.store.connection.execute("SELECT COUNT(*) FROM task_plan_executions WHERE plan_id=? AND tool='apply_patch'", (task["id"],)).fetchone()[0]
        local = ScriptedProvider([final_step("Already fixed; inspect test results"), final_step("review")])
        self.server.tasks.provider_factory_override = lambda *_: local
        resume_event_start = len(self.ws.messages)
        await self.server.tasks.handle(self.ws, {"type":"task.resume", "thread_id":self.thread.id,
            "payload":{"task_id":task["id"], "confirm_workspace":True}}, set())
        await asyncio.gather(*list(self.server.active_turns.values()))
        restored = self.server.store.task_runtime.get(task["id"])
        self.assertEqual(restored["status"], "awaiting_approval", restored["reason"])
        resumed = [e["payload"]["task"] for e in self.ws.messages[resume_event_start:] if e["type"] == "task.updated" and e["payload"]["task"]["status"] == "executing"]
        self.assertTrue(resumed)
        self.assertTrue(all(not t["report"] for t in resumed))
        self.assertEqual(self.server.store.connection.execute("SELECT COUNT(*) FROM task_plan_executions WHERE plan_id=? AND tool='apply_patch'", (task["id"],)).fetchone()[0], original_count)

    async def test_multifile_plan_checkpoint_and_git_review(self):
        (self.repo / "formatting.py").write_text('def title():\n    return "old"\n')
        subprocess.run(["git", "add", "formatting.py"], cwd=self.repo, check=True, capture_output=True)
        subprocess.run(["git", "commit", "-qm", "second file"], cwd=self.repo, check=True, capture_output=True)
        plan = final_step(json.dumps({"steps":[{"description":"Fix addition"},{"description":"Update title"}]}))
        task, _, api = await self.run_task([plan, self.fix(), final_step(),
            tool_step("apply_patch", {"path":"formatting.py", "old_text":'"old"', "new_text":'"new"'}),
            final_step(), final_step("Reviewed both files")])
        self.assertEqual(task["status"], "awaiting_approval", task["reason"])
        self.assertIn("calculator.py", task["report"]["diff"])
        self.assertIn("formatting.py", task["report"]["diff"])
        self.assertTrue(all(step["state"] == "completed" for step in self.server.store.task_plans.get(task["id"])["steps"]))
        self.assertEqual(api.calls, 0)
        self.assertIn('"old"', (self.repo / "formatting.py").read_text())
        self.assertEqual(self.server.store.task_plans.latest_checkpoint(task["id"])["reason"], "task_awaiting_approval")

    async def test_verification_ignores_stale_python_bytecode(self):
        from agent.core.verification import VerificationEngine
        env = dict(os.environ)
        env.pop("PYTHONPYCACHEPREFIX", None)
        env.pop("PYTHONDONTWRITEBYTECODE", None)
        args = ["uv", "run", "--no-project", "python", "-c", "import calculator; print(calculator.add(3,2))"]
        self.assertEqual(subprocess.check_output(args, cwd=self.repo, env=env, text=True).strip(), "1")
        source = self.repo / "calculator.py"
        previous = source.stat()
        source.write_text(source.read_text().replace("a - b", "a + b"), encoding="utf-8")
        os.utime(source, ns=(previous.st_atime_ns, previous.st_mtime_ns))
        self.assertTrue(list((self.repo / "__pycache__").glob("calculator*.pyc")))
        # Demonstrate the dangerous same-size/same-mtime cache hit first.
        self.assertEqual(subprocess.check_output(args, cwd=self.repo, env=env, text=True).strip(), "1")
        async def execute(name, arguments, **kwargs):
            return (await self.project.tools.execute(name, arguments, **kwargs)).to_dict()
        results = await VerificationEngine(self.root / "fresh-logs", execute, 30).run([COMMAND])
        self.assertTrue(all(r["ok"] for r in results), results)

    async def test_pause_before_coroutine_start_preserves_resumable_state(self):
        local = ScriptedProvider([PLAN])
        self.server.tasks.provider_factory_override = lambda *_: local
        await self.server.tasks.handle(self.ws, {"type":"task.start", "thread_id":self.thread.id,
            "payload":{"goal":"Fix calculator", "config":self.config()}}, set())
        task = self.server.store.task_runtime.list(self.thread.id)[0]
        await self.server.tasks.handle(self.ws, {"type":"task.pause", "thread_id":self.thread.id, "payload":{"task_id":task["id"]}}, set())
        self.assertEqual(self.server.store.task_runtime.get(task["id"])["status"], "paused")
        self.assertEqual(local.calls, 0)
        self.assertEqual(self.server.store.task_runtime.usage(task["id"])["api_calls"], 0)

    async def test_model_cannot_replace_project_verification_with_echo(self):
        (self.repo / ".lca").mkdir()
        (self.repo / ".lca/verification.json").write_text(json.dumps({"commands":[COMMAND]}))
        subprocess.run(["git", "add", ".lca"], cwd=self.repo, check=True, capture_output=True)
        subprocess.run(["git", "commit", "-qm", "verification contract"], cwd=self.repo, check=True, capture_output=True)
        config = self.config(local_repairs=0, api_calls=0)
        config["verification_commands"] = []
        task, _, api = await self.run_task([PLAN, tool_step("write_file", {"path":".lca/verification.json", "content":'{"commands":["echo passed"]}'}), final_step()], config=config)
        self.assertEqual(task["status"], "paused", task["reason"])
        self.assertEqual(task["verification"][0]["command"], COMMAND)
        self.assertFalse(task["verification"][0]["ok"])
        self.assertEqual(api.calls, 0)

    async def test_request_timeout_cancellation_and_json_tool_compatibility(self):
        runtime = self.server.store.task_runtime
        config = self.config(request_seconds=1)
        task = runtime.create(self.thread.id, "bounded call", config, str(self.repo))
        guard = BudgetGuard(runtime, task["id"], config["budget"])
        events = []
        async def notify(kind, payload): events.append(kind)
        class Slow(ScriptedProvider):
            async def stream_chat(self, **kwargs):
                self.calls += 1
                await asyncio.sleep(30)
                yield final_step()
        slow = Slow([])
        config["roles"]["planner"]["route"] = "api"
        router = ModelRouter(config, lambda *_: slow, guard, notify)
        with self.assertRaises(ProviderError) as caught:
            await router.text("planner", [{"role":"user", "content":"hello"}])
        self.assertEqual(caught.exception.code, "MODEL_TIMEOUT")
        self.assertEqual(runtime.usage(task["id"])["api_calls"], 1)
        self.assertEqual(slow.calls, 1)
        reserved = runtime.usage(task["id"])["reserved_tokens"]
        request = asyncio.create_task(router.text("planner", [{"role":"user", "content":"hello"}]))
        await asyncio.sleep(.05)
        request.cancel()
        with self.assertRaises(asyncio.CancelledError): await request
        self.assertEqual(runtime.usage(task["id"])["api_calls"], 2)
        self.assertGreater(runtime.usage(task["id"])["reserved_tokens"], reserved)
        config["strategy"] = "local-only"
        config["roles"]["executor"]["tool_mode"] = "json"
        provider = ScriptedProvider([final_step('{"tool_calls":[{"name":"read_file","arguments":{"path":"calculator.py"}}],"content":"inspect"}')])
        router = ModelRouter(config, lambda *_: provider, guard, notify)
        routed = router.resolve("executor")
        chunks = [chunk async for chunk in routed.stream_chat(model="test", messages=[], tools=[{"type":"function", "function":{"name":"read_file"}}])]
        self.assertEqual(chunks[-1].tool_calls[0].name, "read_file")
        self.assertIn("model.compatibility", events)
        self.assertEqual(runtime.usage(task["id"])["api_calls"], 2)

    async def test_frontend_snapshot_matches_backend_and_wrong_thread_cannot_mutate(self):
        task, _, _ = await self.run_task([PLAN, self.fix(), final_step(), final_step("review")])
        events = [e for e in self.ws.messages if e["type"] == "task.updated"]
        self.assertEqual(events[-1]["payload"]["task"]["status"], task["status"])
        self.assertEqual(events[-1]["payload"]["task"]["usage"], self.server.store.task_runtime.usage(task["id"]))
        other = self.project.state.create_thread()
        await self.server.tasks.handle(self.ws, {"type": "task.approve", "thread_id": other.id, "payload": {"task_id": task["id"]}}, set())
        self.assertEqual(self.ws.messages[-1]["type"], "error")
        self.assertEqual(self.server.store.task_runtime.get(task["id"])["status"], "awaiting_approval")


class VerificationTests(unittest.TestCase):
    def test_failure_fingerprint_ignores_attached_duration_units(self):
        from agent.core.verification import failure_fingerprint
        first = [{"command":"tests", "category":"assertion", "exit_code":1, "summary":"AssertionError: 1 != 5\nRan 1 test in 0.001s; 512ms"}]
        second = [{**first[0], "summary":"AssertionError: 1 != 5\nRan 1 test in 0.122s; 810ms"}]
        self.assertEqual(failure_fingerprint(first, "diff"), failure_fingerprint(second, "diff"))

    def test_no_large_model_is_implicitly_selected(self):
        from agent.core.settings import RuntimeSettings
        from agent.llm.ollama import OllamaProvider
        with patch.dict(os.environ, {"LCA_OLLAMA_MODEL":""}):
            self.assertEqual(RuntimeSettings.defaults().ollama_model, "")
            self.assertEqual(OllamaProvider().preferred_model, "")
            RuntimeSettings.validate({"ollama_model":""})

    def test_error_categories(self):
        for code, text, expected in (("PERMISSION_DENIED", "", "permission"), ("COMMAND_TIMEOUT", "", "timeout"),
            ("", "ModuleNotFoundError: abc", "environment"), ("", "ECONNREFUSED", "network"),
            ("", "AssertionError", "assertion"), ("", "no tests ran", "configuration"), ("", "SyntaxError", "code")):
            self.assertEqual(classify({"ok": False, "stderr": text, "error": {"code": code}}), expected)

    def test_no_universal_test_commands_and_custom_configuration(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            self.assertEqual(discover_commands(root, []), [])
            self.assertEqual(discover_commands(root, ["custom-test"]), ["custom-test"])
            (root / ".lca").mkdir()
            (root / ".lca/verification.json").write_text('{"commands":["custom-build"]}')
            self.assertEqual(discover_commands(root, []), ["custom-build"])

    def test_invalid_configuration_rejected(self):
        for raw in ({"strategy": "unlimited"}, {"budget": {"api_calls": -1}}, {"budget": {"api_cost": float("nan")}},
                    {"roles": {"executor": {"output_limit": 0}}}, {"api_key": "must not persist"}):
            with self.assertRaises(ValueError): validate_config(raw)
