"""Current Settings -> durable snapshot -> preflight -> actual Mock HTTP/tools/tests."""
import asyncio
from copy import deepcopy
import json
from pathlib import Path
import unittest

from agent.core.budget import BudgetGuard, BudgetExceeded, DEFAULT_LIMITS, validate_limits
from agent.llm.router import apply_config_overrides
import test_planning_api as http_fixture


class TaskBudgetStartTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = http_fixture.PlanningAPITests.asyncSetUp
    asyncTearDown = http_fixture.PlanningAPITests.asyncTearDown
    config = http_fixture.PlanningAPITests.config
    http = http_fixture.PlanningAPITests.http
    wait = http_fixture.PlanningAPITests.wait
    diagnostics = http_fixture.PlanningAPITests.diagnostics

    async def save(self, config):
        catalog = {"connections":[{"connection_id":"online", "display_name":"Mock API",
            "provider_type":"openai_compatible", "base_url":"http://127.0.0.1:9/v1",
            "credential_reference":None, "enabled":True}], "profiles":[]}
        for role, binding in config["roles"].items():
            catalog["profiles"].append({"model_profile_id":"online-" + role, "connection_id":"online",
                "model_id":binding["model"], "display_name":role, "context_window":65536,
                "max_output_tokens":binding["output_limit"]})
            binding["model_profile_id"] = "online-" + role
        await self.server.tasks.handle(self.ws, {"type":"task.catalog.update",
            "payload":{"catalog":catalog, "config":config}}, set())
        self.assertEqual(self.ws.messages[-1]["type"], "task.loaded", self.ws.messages[-1])

    def online(self, **limits):
        config = self.config(**limits)
        config["strategy"] = "api-only"
        return config

    async def start_current(self, overrides=None):
        payload = {"goal":"Fix calculator addition"}
        if overrides is not None: payload["config_overrides"] = overrides
        await self.server.tasks.handle(self.ws, {"type":"task.start", "thread_id":self.thread.id,
            "payload":payload}, set())
        self.assertEqual(self.ws.messages[-1]["type"], "task.loaded", self.ws.messages[-1])
        return self.server.store.task_runtime.list(self.thread.id)[0]

    async def test_online_bound_first_request_default_tokens_real_code_tests_and_diff(self):
        await self.http([http_fixture.VALID])
        await self.save(self.online(api_calls=6))
        await self.start_current({})
        task = await self.wait()
        self.assertEqual(task["status"], "awaiting_approval", task["reason"])
        self.assertEqual(self.requests[0]["model"], "planner")
        self.assertEqual(len(self.requests), 4)
        self.assertEqual(task["config"]["budget"]["api_tokens"], DEFAULT_LIMITS['api_tokens'])
        self.assertTrue(all(v["ok"] for v in task["verification"]))
        self.assertIn("a + b", Path(task["workspace"], "calculator.py").read_text())
        self.assertIn("a - b", (self.repo / "calculator.py").read_text())
        self.assertIn("+    return a + b", task["report"]["diff"])
        report = self.diagnostics(task)
        self.assertEqual(report["usage"]["api_calls"], 4)
        self.assertEqual(report["usage"]["reserved_tokens"], 480)
        self.assertEqual(report["config_source"], "saved-settings")

    async def test_explicit_zero_task_and_global_limits_block_before_http_with_details(self):
        await self.http([http_fixture.VALID])
        for field in ("api_calls", "api_tokens", "global_api_calls", "global_api_tokens"):
            with self.subTest(field=field):
                await self.save(self.online(**{field:0}))
                await self.start_current({})
                task = await self.wait()
                self.assertEqual(task["status"], "paused", task["reason"])
                self.assertEqual(self.requests, [])
                report = self.diagnostics(task)
                self.assertEqual(report["usage"]["api_calls"], 0)
                self.assertEqual(report["usage"]["reserved_tokens"], 0)
                detail = report["last_error"]["budget"]
                self.assertEqual(detail["field"], field)
                self.assertEqual(detail["scope"], "global" if field.startswith("global_") else "task")
                self.assertEqual((detail["limit"],detail["used"]), (0,0))
                self.assertGreater(detail["required"], 0)
                self.assertFalse(detail["request_sent"])
                self.assertIn(field, task["reason"])
                self.assertEqual(report["calls"], [])

    async def test_settings_changed_after_panel_load_new_task_uses_latest_planner_and_budget(self):
        await self.http([http_fixture.VALID])
        old = self.online(api_calls=0, api_tokens=0)
        old["strategy"] = "local-only"
        old["roles"]["planner"]["model"] = "stale-planner"
        await self.save(old)
        # Represents the old Task panel mount; unchanged fields now send {}.
        cached = deepcopy(self.server.tasks.settings())
        await self.save(self.online(api_calls=6, api_tokens=30000))
        await self.start_current({})
        task = await self.wait()
        self.assertEqual(cached["budget"]["api_calls"], 0)
        self.assertEqual(task["config"]["strategy"], "api-only")
        self.assertEqual(task["config"]["budget"]["api_calls"], 6)
        self.assertEqual(task["resolved_roles"]["planner"]["model"], "planner")
        self.assertEqual(task["status"], "awaiting_approval", task["reason"])
        self.assertEqual(self.requests[0]["model"], "planner")

    async def test_settings_changes_do_not_mutate_old_snapshot_or_resume_budget(self):
        await self.http([http_fixture.VALID])
        await self.save(self.online(api_calls=0))
        old = await self.start_current()
        await self.wait()
        old = self.server.tasks.runtime.get(old["id"])
        updated = self.online(api_calls=6)
        updated["roles"]["planner"]["model"] = "new-planner"
        await self.save(updated)
        await self.server.tasks.handle(self.ws, {"type":"task.resume", "thread_id":self.thread.id,
            "payload":{"task_id":old["id"], "confirm_workspace":True}}, set())
        await self.wait()
        resumed = self.server.tasks.runtime.get(old["id"])
        for key in ("config", "resolved_roles", "global_budget", "config_snapshot_at"):
            self.assertEqual(resumed[key], old[key])
        self.assertEqual(self.requests, [])
        new = await self.start_current()
        await self.wait()
        self.assertEqual(new["config"]["budget"]["api_calls"], 6)
        self.assertEqual(new["resolved_roles"]["planner"]["model"], "new-planner")

    async def test_first_reservation_exceeds_token_cap_despite_zero_usage(self):
        await self.http([http_fixture.VALID])
        config = self.online(api_calls=6)
        config["roles"]["planner"]["output_limit"] = 32768
        await self.save(config)
        await self.start_current()
        task = await self.wait()
        detail = self.diagnostics(task)["last_error"]["budget"]
        self.assertEqual(detail["field"], "api_tokens")
        self.assertEqual(detail["used"], 0)
        self.assertEqual(detail["output_limit"], 32768)
        self.assertEqual(detail["required"], detail["input_token_estimate"] + 32768)
        self.assertEqual(self.requests, [])

    async def test_other_task_usage_blocks_global_limit_but_current_task_usage_zero(self):
        await self.http([http_fixture.VALID])
        await self.save(self.online(api_calls=6, global_api_calls=4))
        await self.start_current()
        first = await self.wait()
        self.assertEqual(first["status"], "awaiting_approval", first["reason"])
        await self.start_current()
        second = await self.wait()
        detail = self.diagnostics(second)["last_error"]["budget"]
        self.assertEqual((detail["field"],detail["limit"],detail["used"],detail["required"]), ("global_api_calls",4,4,1))
        self.assertEqual(self.server.tasks.runtime.usage(second["id"])["api_calls"], 0)
        self.assertEqual(len(self.requests), 4)

    async def test_explicit_zero_override_survives_nonzero_saved_defaults(self):
        await self.http([http_fixture.VALID])
        await self.save(self.online(api_calls=6))
        await self.start_current({"budget":{"api_calls":0}})
        task = await self.wait()
        self.assertEqual(task["config_source"], "saved-settings-with-overrides")
        self.assertEqual(task["last_error"]["budget"]["field"], "api_calls")
        self.assertEqual(self.server.tasks.settings()["budget"]["api_calls"], 6)
        self.assertEqual(self.requests, [])

    async def test_exact_limit_allows_first_reservation_and_next_is_blocked(self):
        await self.save(self.online())
        task = self.server.tasks.runtime.create(self.thread.id, "test", self.online(api_calls=1), str(self.repo))
        guard = BudgetGuard(self.server.tasks.runtime, task["id"], DEFAULT_LIMITS)
        kwargs = dict(route="api",role="planner",model="planner",messages=[],tools=[],context_window=65536,output_limit=1024)
        tokens = len(json.dumps({"messages":[], "tools":[]}).encode()) + 256 + 1024
        task["config"]["budget"]["api_tokens"] = tokens
        self.server.tasks.runtime.save(task)
        request = guard.reserve(**kwargs)
        self.assertEqual(self.server.tasks.runtime.usage(task["id"])["reserved_tokens"], tokens)
        with self.assertRaises(BudgetExceeded) as caught: guard.reserve(**kwargs)
        self.assertEqual(caught.exception.details["field"], "api_calls")
        guard.finish(request, "completed", {"input_tokens":10,"output_tokens":5,"estimated":False})
        self.assertEqual(self.server.tasks.runtime.usage(task["id"])["reserved_tokens"], 15)


class BudgetConfigTests(unittest.TestCase):
    def test_serialized_zero_missing_and_null_are_distinct(self):
        self.assertEqual(validate_limits(json.loads('{"api_calls":0,"api_tokens":0}'))["api_calls"], 0)
        self.assertEqual(validate_limits({})["api_calls"], 200)
        self.assertEqual(validate_limits({})["api_tokens"], 10000000)
        for field in ("api_calls","api_tokens","global_api_calls","global_api_tokens"):
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, field): validate_limits({field:None})

    def test_overrides_merge_latest_nested_fields_without_resetting_other_roles(self):
        from agent.llm.router import validate_config
        saved = validate_config({"budget":{"api_calls":8}, "roles":{"planner":{"model":"latest"}}})
        result = apply_config_overrides(saved, {"budget":{"api_tokens":0}, "roles":{"executor":{"output_limit":256}}})
        self.assertEqual(result["budget"]["api_calls"], 8)
        self.assertEqual(result["budget"]["api_tokens"], 0)
        self.assertEqual(result["roles"]["planner"]["model"], "latest")
        self.assertEqual(result["roles"]["executor"]["output_limit"], 256)
        self.assertEqual(saved["budget"]["api_tokens"], 10000000)
        for patch in ({"budget":None},{"roles":{"unknown":{}}},{"roles":{"planner":0}}, {"unknown":1}):
            with self.subTest(patch=patch), self.assertRaises(ValueError): apply_config_overrides(saved, patch)
