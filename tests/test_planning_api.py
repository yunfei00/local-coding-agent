"""A-J: real HTTP/Agent/worktree/files/unittest; no external API or credentials."""
import asyncio
import json
from pathlib import Path
import unittest
from dataclasses import asdict

from aiohttp import web
from agent.llm.openai_compatible import OpenAICompatibleProvider
from agent.llm.router import validate_config, ModelRouter
from agent.llm.base import ProviderError
from agent.core.budget import BudgetGuard
from test_agent_reliability import ScriptedProvider, final_step
import test_v04_orchestration as fixture

VALID = {"steps":[{"description":"Fix calculator addition with tools and verify"}]}


class PlanningAPITests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = fixture.TaskTests.asyncSetUp
    asyncTearDown = fixture.TaskTests.asyncTearDown
    config = fixture.TaskTests.config

    async def http(self, plans, *, wire="sse", block=False):
        self.requests, self.plans = [], list(plans)
        self.entered, self.release = asyncio.Event(), asyncio.Event()
        self.block = block

        async def chat(request):
            body = await request.json()
            self.requests.append(body)
            role = body["model"]
            if role == "planner":
                self.entered.set()
                if self.block:
                    await self.release.wait()
                answer = self.plans.pop(0) if self.plans else "invalid-" + str(len(self.requests))
                if wire == "http-error":
                    return web.json_response({"error":{"message":"SENSITIVE_FILE_CONTENT mock-secret-key"}}, status=429)
                if isinstance(answer, dict):
                    content = json.dumps(answer, ensure_ascii=False)
                else:
                    content = answer
                message = {"content":content}
                if wire in {"tool", "json-tool", "fragmented-tool"}:
                    message = {"content":None, "tool_calls":[{"index":0,"id":"plan-call", "type":"function",
                        "function":{"name":"submit_plan", "arguments":content}}]}
            elif role == "executor":
                if any(m["role"] == "tool" for m in body["messages"]):
                    message = {"content":"Implementation done"}
                else:
                    message = {"tool_calls":[{"index":0,"id":"patch-call", "type":"function", "function":{
                        "name":"apply_patch", "arguments":json.dumps({"path":"calculator.py", "old_text":"return a - b", "new_text":"return a + b"})}}]}
            else:
                message = {"content":"Review the tests and Diff"}
            finish = "tool_calls" if message.get("tool_calls") else "stop"
            usage = {"prompt_tokens":100, "completion_tokens":20, "prompt_tokens_details":{"cached_tokens":5}}
            if wire in {"json", "json-tool"}:
                return web.json_response({"choices":[{"message":message, "finish_reason":finish}], "usage":usage})
            if wire == "truncated": finish = "length"
            if wire == "empty": message = {"content":""}
            payload = {"choices":[{"delta":message,"finish_reason":finish}]}
            tail = {"choices":[], "usage":usage}
            raw = ("data: " + json.dumps(payload, ensure_ascii=False) + "\n\ndata: " + json.dumps(tail) + "\n\ndata: [DONE]\n\n").encode()
            if wire == "fragmented-tool" and role == "planner":
                call = message["tool_calls"][0]
                args = call["function"]["arguments"]
                parts = [{"choices":[{"delta":{"tool_calls":[{"index":0,"id":"plan-call", "function":{"name":"submit_","arguments":args[:5]}}]},"finish_reason":None}]},
                    {"choices":[{"delta":{"tool_calls":[{"index":0,"function":{"name":"plan","arguments":args[5:]}}]}, "finish_reason":"tool_calls"}]}, tail]
                raw = ("".join("data: " + json.dumps(p) + "\n\n" for p in parts) + "data: [DONE]\n\n").encode()
            response = web.StreamResponse(headers={"Content-Type":"text/event-stream"})
            try:
                await response.prepare(request)
                if wire == "fragmented":
                    for offset in range(0, len(raw), 3):
                        await response.write(raw[offset:offset+3])
                        await asyncio.sleep(0)
                else:
                    await response.write(raw)
                await response.write_eof()
            except (ConnectionResetError, RuntimeError):
                pass
            return response

        app = web.Application()
        app.router.add_post("/v1/chat/completions", chat)
        runner = web.AppRunner(app, shutdown_timeout=0.1)
        await runner.setup()
        async def cleanup():
            self.release.set()
            await runner.cleanup()
        self.addAsyncCleanup(cleanup)
        site = web.TCPSite(runner, "127.0.0.1", 0)
        await site.start()
        url = "http://127.0.0.1:" + str(site._server.sockets[0].getsockname()[1]) + "/v1"
        self.factory = lambda route, profile: OpenAICompatibleProvider(base_url=url, api_key="mock-secret-key",
            preferred_model=profile["model"], context_window=65536)
        self.server.tasks.provider_factory_override = self.factory
        self.server.openai_api_key = "mock-secret-key"

    async def start(self, **budget):
        config = self.config(api_calls=20, api_tokens=250000, **budget)
        config["strategy"] = "api-only"
        await self.server.tasks.handle(self.ws, {"type":"task.start", "thread_id":self.thread.id,
            "payload":{"goal":"Fix calculator addition; SENSITIVE_GOAL", "config":config}}, set())
        return self.server.store.task_runtime.list(self.thread.id)[0]

    async def wait(self):
        await asyncio.wait_for(asyncio.gather(*list(self.server.active_turns.values())), 120)
        return self.server.store.task_runtime.list(self.thread.id)[0]

    def diagnostics(self, task):
        result = self.server.tasks.diagnostics(task["id"])
        text = json.dumps(result["diagnostics"])
        for secret in ("SENSITIVE_GOAL", "SENSITIVE_FILE_CONTENT", "mock-secret-key", "return a - b", "Authorization", "Cookie"):
            self.assertNotIn(secret, text)
        for path in result["paths"].values(): self.assertTrue(Path(path).is_file())
        return result["diagnostics"]["json"]

    async def test_a_normal_plan_executes_real_patch_unittest_diff_and_settles_usage(self):
        await self.http([VALID])
        await self.start()
        task = await self.wait()
        self.assertEqual(task["status"], "awaiting_approval", task["reason"])
        self.assertTrue(all(v["ok"] for v in task["verification"]))
        self.assertIn("a + b", Path(task["workspace"], "calculator.py").read_text())
        self.assertIn("a - b", (self.repo / "calculator.py").read_text())
        self.assertIn("+    return a + b", task["report"]["diff"])
        report = self.diagnostics(task)
        self.assertEqual(report["usage"]["api_calls"], len(self.requests))
        self.assertEqual(report["usage"]["reserved_tokens"], 120 * len(self.requests))
        self.assertGreater(report["usage"]["released_tokens"], 0)
        planner = report["calls"][0]["metadata"]
        self.assertTrue(planner["schema_valid"])
        self.assertEqual(planner["next_state"], "executing")
        self.assertEqual(planner["http_status"], 200)
        self.assertEqual(planner["sequence"], 1)

    async def test_b_c_invalid_json_and_schema_feedback_recover(self):
        await self.http(["not JSON", {"steps":"bad"}, VALID])
        await self.start()
        task = await self.wait()
        self.assertEqual(task["status"], "awaiting_approval", task["reason"])
        self.assertEqual(task["planning_attempts"], 3)
        report = self.diagnostics(task)
        self.assertEqual([c["metadata"].get("error_code") for c in report["calls"][:2]], ["PLAN_JSON_INVALID", "PLAN_SCHEMA_INVALID"])
        self.assertIn("schema", json.dumps(self.requests[2]["messages"]).lower())

    async def test_d_tcp_fragmentation_reassembles_unicode_plan(self):
        await self.http([{"steps":[{"description":"修复 calculator addition"}]}], wire="fragmented")
        await self.start()
        task = await self.wait()
        self.assertEqual(task["status"], "awaiting_approval", task["reason"])
        self.assertTrue(self.diagnostics(task)["planned"])

    async def test_e_non_streaming_json_and_native_tool_plan(self):
        for wire in ("json", "tool", "json-tool", "fragmented-tool"):
            with self.subTest(wire=wire):
                await self.http([VALID], wire=wire)
                await self.start()
                task = await self.wait()
                self.assertEqual(task["status"], "awaiting_approval", task["reason"])
                self.assertTrue(self.diagnostics(task)["calls"][0]["metadata"]["schema_valid"])

    async def test_f_identical_invalid_plan_stops_at_two_even_with_large_budget(self):
        await self.http(["same invalid", "same invalid", VALID])
        await self.start()
        task = await self.wait()
        self.assertEqual(task["last_error"]["code"], "PLAN_NO_PROGRESS")
        self.assertEqual(len(self.requests), 2)
        self.assertEqual(self.diagnostics(task)["why_not_executing"], "PLAN_NO_PROGRESS")

    async def test_g_diagnosis_cannot_reset_persistent_planning_limit(self):
        await self.http([])
        local = ScriptedProvider([final_step("bad-" + str(i)) for i in range(4)])
        self.server.tasks.provider_factory_override = lambda route, p: local if route == "local" else self.factory(route,p)
        config = self.config(api_calls=20, local_repairs=1)
        await self.server.tasks.handle(self.ws, {"type":"task.start", "thread_id":self.thread.id,
            "payload":{"goal":"Fix calculator", "config":config}}, set())
        task = await self.wait()
        self.assertEqual(task["last_error"]["code"], "PLAN_RETRY_LIMIT")
        self.assertEqual(task["planning_attempts"], 4)
        self.assertEqual(task["escalations"], 1)
        self.assertEqual(len(self.requests), 1)
        self.assertEqual(local.calls, 4)
        self.diagnostics(task)

    async def test_h_budget_exhaustion_prevents_additional_http(self):
        for limits in ({"api_calls":0}, {"api_calls":1}, {"api_tokens":1}):
            with self.subTest(limits=limits):
                await self.http(["invalid", VALID])
                config = self.config(**limits)
                config["strategy"] = "api-only"
                await self.server.tasks.handle(self.ws, {"type":"task.start", "thread_id":self.thread.id,
                    "payload":{"goal":"Fix calculator", "config":config}}, set())
                task = await self.wait()
                self.assertEqual(task["last_error"]["code"], "BUDGET_EXHAUSTED")
                self.assertEqual(len(self.requests), 1 if limits.get("api_calls") == 1 else 0)
                self.diagnostics(task)

    async def test_i_cancel_during_planning_preserves_uncertain_reservation(self):
        await self.http([VALID], block=True)
        task = await self.start()
        await asyncio.wait_for(self.entered.wait(), 5)
        await self.server.tasks.handle(self.ws, {"type":"task.cancel", "thread_id":self.thread.id,
            "payload":{"task_id":task["id"]}}, set())
        self.release.set()
        task = self.server.store.task_runtime.get(task["id"])
        self.assertEqual(task["status"], "cancelled")
        report = self.diagnostics(task)
        self.assertEqual(report["calls"][0]["status"], "cancelled")
        self.assertGreater(report["usage"]["reserved_tokens"], 0)
        self.assertEqual(report["usage"]["released_tokens"], 0)
        self.assertEqual(len(self.requests), 1)

    async def test_j_pause_resume_keeps_counter_and_budget_ids(self):
        await self.http([VALID, VALID], block=True)
        task = await self.start()
        await asyncio.wait_for(self.entered.wait(), 5)
        await self.server.tasks.handle(self.ws, {"type":"task.pause", "thread_id":self.thread.id,
            "payload":{"task_id":task["id"]}}, set())
        first = self.server.store.task_runtime.calls(task["id"])[0]["id"]
        self.block = False
        self.release.set()
        await self.server.tasks.handle(self.ws, {"type":"task.resume", "thread_id":self.thread.id,
            "payload":{"task_id":task["id"], "confirm_workspace":True}}, set())
        task = await self.wait()
        self.assertEqual(task["status"], "awaiting_approval", task["reason"])
        self.assertEqual(task["planning_attempts"], 2)
        report = self.diagnostics(task)
        self.assertEqual(len([c for c in report["calls"] if c["call_id"] == first]), 1)
        self.assertEqual(report["usage"]["api_calls"], len(self.requests))

    async def test_http_error_diagnostics_exclude_gateway_echo(self):
        await self.http([VALID], wire="http-error")
        await self.start()
        task = await self.wait()
        report = self.diagnostics(task)
        self.assertEqual(report["last_error_code"], "OPENAI_COMPATIBLE_RATE_LIMITED")
        self.assertEqual(report["calls"][0]["metadata"]["http_status"], 429)
        self.assertNotIn("SENSITIVE_FILE_CONTENT", task["reason"])

    async def test_truncated_and_empty_response_are_specific_bounded_errors(self):
        for wire, code in (("truncated","PLAN_TRUNCATED"), ("empty","PLAN_EMPTY")):
            with self.subTest(wire=wire):
                await self.http([VALID], wire=wire)
                await self.start()
                task = await self.wait()
                report = self.diagnostics(task)
                self.assertEqual(report["calls"][0]["metadata"]["error_code"], code)
                self.assertLessEqual(len(self.requests), 4)
                self.assertEqual(task["status"], "paused")

    async def test_planning_counter_cannot_reset_on_resume_after_limit(self):
        await self.http(["invalid-" + str(i) for i in range(10)])
        await self.start()
        task = await self.wait()
        before = len(self.requests)
        self.assertEqual(before, 4)
        await self.server.tasks.handle(self.ws,{"type":"task.resume","thread_id":self.thread.id,
            "payload":{"task_id":task["id"],"confirm_workspace":True}},set())
        task = await self.wait()
        self.assertEqual(len(self.requests),before)
        self.assertEqual(task["last_error"]["code"],"PLAN_RETRY_LIMIT")

    async def test_json_array_is_parsed_but_fails_schema(self):
        await self.http(["[]", VALID])
        await self.start()
        task = await self.wait()
        self.assertEqual(task["status"], "awaiting_approval", task["reason"])
        meta = self.diagnostics(task)["calls"][0]["metadata"]
        self.assertTrue(meta["parse_success"])
        self.assertFalse(meta["schema_valid"])
        self.assertEqual(meta["error_code"], "PLAN_SCHEMA_INVALID")

    async def test_json_tool_compatibility_accepts_direct_plan_without_native_tools(self):
        config = self.config()
        config["roles"]["planner"]["tool_mode"] = "json"
        task, local, api = await fixture.TaskTests.run_task(self,
            [fixture.PLAN, fixture.TaskTests.fix(self), final_step(), final_step("review")], config=config)
        self.assertEqual(task["status"], "awaiting_approval", task["reason"])
        self.assertEqual(api.calls, 0)
        self.assertTrue(self.diagnostics(task)["planned"])

    async def test_policy_conflict_is_diagnosed_before_worktree_or_http(self):
        await self.http([VALID])
        config = self.config()
        config["strategy"] = "api-only"
        runtime = self.server.store.task_runtime
        task = runtime.create(self.thread.id, "goal", config, str(self.repo))
        task["provider_settings"] = asdict(self.server.settings)
        task["resolved_roles"] = config["roles"]
        task["resolved_roles"]["planner"]["_connection"] = {"provider_type":"ollama"}
        runtime.save(task)
        self.server.tasks.launch(self.ws, task, self.project, set())
        task = await self.wait()
        self.assertEqual(task["workspace"], "")
        self.assertEqual(len(self.requests), 0)
        report = self.diagnostics(task)
        self.assertEqual(report["last_error_code"], "MODEL_POLICY_MISMATCH")
        self.assertEqual(report["last_error"]["role"], "planner")

    async def test_timeout_has_typed_failure_and_retains_uncertain_usage(self):
        await self.http([VALID], block=True)
        await self.start(request_seconds=1)
        task = await self.wait()
        self.release.set()
        report = self.diagnostics(task)
        self.assertEqual(report["last_error_code"], "MODEL_TIMEOUT")
        self.assertEqual(report["usage"]["api_calls"], 1)
        self.assertGreater(report["usage"]["reserved_tokens"], 0)
        self.assertEqual(report["usage"]["released_tokens"], 0)

    async def test_request_not_dispatched_releases_admission_without_api_call(self):
        runtime = self.server.store.task_runtime
        config = self.config()
        config["strategy"] = "api-only"
        task = runtime.create(self.thread.id, "goal", config, str(self.repo))
        guard = BudgetGuard(runtime, task["id"], config["budget"])
        provider = ScriptedProvider([fixture.PLAN])
        async def disconnected(*args): raise RuntimeError("UI disconnected")
        router = ModelRouter(config, lambda route,p:provider, guard, disconnected)
        with self.assertRaises(ProviderError) as error:
            await router.plan([{"role":"user", "content":"plan"}])
        self.assertEqual(error.exception.code, "MODEL_CLIENT_ERROR")
        self.assertEqual(provider.calls, 0)
        self.assertEqual(runtime.usage(task["id"])["api_calls"], 0)
        self.assertEqual(runtime.usage(task["id"])["reserved_tokens"], 0)
        self.assertEqual(runtime.calls(task["id"])[0]["status"], "not_sent")

    async def test_diagnostics_redaction_preserves_json_numeric_types_and_omits_bodies(self):
        await self.http([VALID])
        await self.start()
        task = await self.wait()
        runtime = self.server.store.task_runtime
        call = runtime.calls(task["id"])[0]
        guard = BudgetGuard(runtime,task["id"],self.config()["budget"])
        guard.annotate(call["id"], {"prompt":"SENSITIVE_GOAL", "Cookie":"cookie-secret", "Authorization":"Bearer mock-secret-key"})
        self.server.tasks.credentials["connection-numeric-test"] = "100"
        report = self.diagnostics(task)
        self.assertIsInstance(report["calls"][0]["metadata"]["input_tokens"], int)
        self.assertNotIn("cookie-secret", json.dumps(report))
