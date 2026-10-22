"""Real HTTP clients, distinct endpoints, durable role snapshots; no paid API."""
import asyncio
from copy import deepcopy
import json
from pathlib import Path
import unittest

from aiohttp import web

from agent.core.model_catalog import ModelCatalog, validate_catalog, KEY
from agent.core.budget import BudgetGuard
from agent.llm.router import ModelRouter, validate_config
from agent.llm.base import ProviderError
import test_v04_orchestration as legacy


class MixedProviderTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = legacy.TaskTests.asyncSetUp
    asyncTearDown = legacy.TaskTests.asyncTearDown
    config = legacy.TaskTests.config

    async def setup_catalog(self, *, broken=False, failure=False, slow=False):
        self.requests = []
        self.failed_once = False
        self.runners = []
        connections, profiles = [], []
        for index, provider_type in enumerate(("ollama", "ollama", "openai_compatible", "openai_compatible")):
            cid = "service-" + str(index)
            async def handler(request, index=index):
                if request.path.endswith("tags"):
                    return web.json_response({"models": [{"name":"same-name"}]})
                if request.path.endswith("models"):
                    return web.json_response({"data": [{"id":"same-name"}]})
                body = await request.json()
                if request.path.endswith("show"):
                    return web.json_response({"capabilities":["tools"]})
                self.requests.append((index, body, request.headers.get("Authorization")))
                if broken and index == 3:
                    return web.json_response({"error":{"message":"rate limited"}}, status=429)
                if slow and index == 3:
                    await asyncio.sleep(1.5)
                if index >= 2:
                    text = "Change subtraction to addition; let the local Executor apply it."
                    payload = {"choices":[{"delta":{"content":text},"finish_reason":"stop"}],
                               "usage":{"prompt_tokens":120,"completion_tokens":30,"prompt_tokens_details":{"cached_tokens":20},"cost":0.001}}
                    return web.Response(text="data: " + json.dumps(payload) + "\n\ndata: [DONE]\n\n", content_type="text/event-stream")
                messages = body["messages"]
                if index == 0:
                    text = json.dumps({"steps":[{"description":"Fix calculator using tools"}]})
                    return web.json_response({"message":{"content":text},"done":True,"prompt_eval_count":30,"eval_count":20})
                system = " ".join(str(m.get("content", "")) for m in messages if m["role"] == "system")
                if "Review the bounded evidence" in system:
                    message = {"content":"Independent tests passed; inspect Diff."}
                elif any(m["role"] == "tool" for m in messages):
                    message = {"content":"Implementation complete"}
                else:
                    if failure and not self.failed_once:
                        self.failed_once = True
                        old, new = "a - b", "a * b"
                    else:
                        old, new = ("a * b" if failure else "a - b"), "a + b"
                    message = {"content":"", "tool_calls":[{"function":{"name":"apply_patch", "arguments":{"path":"calculator.py","old_text":old,"new_text":new}}}]}
                return web.json_response({"message":message, "done":True,"prompt_eval_count":120,"eval_count":30})
            app = web.Application()
            app.router.add_route("*", "/{tail:.*}", handler)
            runner = web.AppRunner(app)
            await runner.setup()
            self.addAsyncCleanup(runner.cleanup)
            site = web.TCPSite(runner, "127.0.0.1", 0)
            await site.start()
            self.runners.append(runner)
            port = site._server.sockets[0].getsockname()[1]
            connections.append({"connection_id":cid,"display_name":"Service " + str(index),"provider_type":provider_type,
                "base_url":f"http://127.0.0.1:{port}" + ("/v1" if index >= 2 else ""),"credential_reference":"connection-" + cid if index >= 2 else None,"enabled":True})
            profiles.append({"model_profile_id":"model-" + str(index), "connection_id":cid, "model_id":"same-name", "display_name":"Same name " + str(index),"context_window":65536,"max_output_tokens":1024})
        self.catalog = validate_catalog({"connections":connections,"profiles":profiles})
        self.server.tasks.credentials = {"connection-service-2":"secret-two", "connection-service-3":"secret-three"}
        self.server.store.set_setting(KEY, json.dumps(self.catalog))
        self.cfg = self.config(local_repairs=1)
        for role, index in (("planner",0),("executor",1),("reviewer",1),("escalation",3)):
            self.cfg["roles"][role]["model_profile_id"] = "model-" + str(index)

    async def close_http(self):
        await asyncio.gather(*(runner.cleanup() for runner in self.runners))

    async def start(self, config=None):
        await self.server.tasks.handle(self.ws, {"type":"task.start", "thread_id":self.thread.id,
            "payload":{"goal":"Fix calculator addition", "config":config or self.cfg}}, set())
        await asyncio.wait_for(asyncio.gather(*list(self.server.active_turns.values())), 30)
        return self.server.store.task_runtime.list(self.thread.id)[0]

    async def test_four_profiles_same_names_and_independent_roles(self):
        await self.setup_catalog()
        cfg = deepcopy(self.cfg)
        cfg["roles"]["reviewer"]["model_profile_id"] = "model-2"
        resolved = self.server.tasks.catalog().resolve(cfg)
        router = ModelRouter(cfg, lambda route,p:self.server.tasks.make_provider({},route,p), None, None, resolved["roles"])
        clients = [router.resolve(role) for role in cfg["roles"]]
        self.assertEqual(len({p.provider.base_url for p in clients}), 4)
        self.assertEqual([p.route for p in clients], ["local","local","api","api"])
        self.assertEqual(len({p.preferred_model for p in clients}), 1)

    async def test_http_local_success_no_api_and_real_journal(self):
        await self.setup_catalog()
        task = await self.start()
        self.assertEqual(task["status"], "awaiting_approval", task["reason"])
        self.assertTrue(all(index < 2 for index,_,_ in self.requests))
        calls = self.server.tasks.public(task)["calls"]
        self.assertEqual([c["role"] for c in calls], ["planner","executor","executor","reviewer"])
        self.assertEqual(calls[0]["usage"]["connection_id"], "service-0")
        self.assertEqual(self.server.tasks.runtime.usage(task["id"])["api_calls"], 0)

    async def test_explicit_api_reviewer_uses_its_own_connection(self):
        await self.setup_catalog()
        self.cfg["roles"]["reviewer"]["model_profile_id"] = "model-2"
        task = await self.start()
        self.assertEqual(task["status"], "awaiting_approval", task["reason"])
        self.assertEqual([i for i,_,_ in self.requests if i >= 2], [2])
        self.assertEqual(self.requests[-1][2], "Bearer secret-two")
        self.assertEqual(self.server.tasks.runtime.usage(task["id"])["api_calls"], 1)

    async def test_http_escalation_specific_endpoint_usage_then_local(self):
        await self.setup_catalog(failure=True)
        task = await self.start()
        self.assertEqual(task["status"], "awaiting_approval", task["reason"])
        indexes = [r[0] for r in self.requests]
        api_index = indexes.index(3)
        self.assertEqual(indexes.count(3), 1)
        self.assertEqual(indexes[api_index+1], 1)
        self.assertNotIn(2, indexes)
        body = self.requests[api_index][1]
        self.assertFalse(body.get("tools"))
        self.assertEqual(body["model"], "same-name")
        self.assertEqual(self.requests[api_index][2], "Bearer secret-three")
        usage = self.server.tasks.runtime.usage(task["id"])
        self.assertEqual((usage["api_calls"], usage["input_tokens"],usage["output_tokens"],usage["cached_tokens"]), (1,120,30,20))
        self.assertFalse(usage["estimated"])
        self.assertNotIn("secret-three", json.dumps(self.server.tasks.public(task)))

    async def test_local_only_and_zero_or_exhausted_api_limits(self):
        for mode, limit in (("local-only",{}),("local-first",{"api_calls":0}),("local-first",{"api_tokens":1})):
            await self.setup_catalog(failure=True)
            self.cfg["strategy"] = mode
            self.cfg["budget"].update(limit)
            task = await self.start()
            self.assertEqual(task["status"], "paused", task["reason"])
            self.assertFalse(any(i >= 2 for i,_,_ in self.requests))

    async def test_http_rate_limit_reservation_retained(self):
        await self.setup_catalog(failure=True, broken=True)
        task = await self.start()
        self.assertEqual(task["status"], "paused")
        self.assertEqual(self.server.tasks.runtime.usage(task["id"])["api_calls"], 1)
        self.assertEqual(sum(i==3 for i,_,_ in self.requests), 1)

    async def test_http_timeout_reservation_retained(self):
        await self.setup_catalog(failure=True, slow=True)
        self.cfg["budget"]["request_seconds"] = 1
        task = await self.start()
        self.assertEqual(task["status"], "paused")
        self.assertIn("timed out", task["reason"])
        self.assertEqual(self.server.tasks.runtime.usage(task["id"])["api_calls"], 1)

    async def test_snapshot_restart_catalog_changes_preserve_roles_and_budget(self):
        await self.setup_catalog(failure=True, broken=True)
        task = await self.start()
        before = deepcopy(task["resolved_roles"])
        usage = self.server.tasks.runtime.usage(task["id"])
        self.catalog["connections"][1]["base_url"] = "http://127.0.0.1:1"
        self.catalog["profiles"][1]["model_id"] = "changed"
        await self.server.tasks.handle(self.ws, {"type":"task.catalog.update", "payload":{"catalog":self.catalog,"config":self.cfg}}, set())
        from agent.core.task_runtime import TaskRuntimeStore
        recovered = TaskRuntimeStore(self.server.store.task_plans)
        recovered.recover()
        self.assertEqual(recovered.get(task["id"])["resolved_roles"], before)
        self.assertEqual(recovered.usage(task["id"]), usage)
        self.assertIsNotNone(recovered.plans.latest_checkpoint(task["id"]))
        await self.server.tasks.handle(self.ws, {"type":"task.resume", "thread_id":self.thread.id,
            "payload":{"task_id":task["id"],"confirm_workspace":True}}, set())
        await asyncio.wait_for(asyncio.gather(*list(self.server.active_turns.values())), 30)
        resumed = recovered.get(task["id"])
        self.assertEqual(resumed["status"], "awaiting_approval", resumed["reason"])
        self.assertEqual(resumed["resolved_roles"], before)
        self.assertEqual(recovered.usage(task["id"])["api_calls"], usage["api_calls"])

    async def test_settings_change_during_planning_does_not_reroute_executor(self):
        await self.setup_catalog()
        original_send = self.ws.send_json
        async def send(event):
            await original_send(event)
            if event["type"] == "model.active" and event["payload"]["role"] == "planner":
                updated = deepcopy(self.cfg)
                updated["roles"]["executor"]["model_profile_id"] = "model-3"
                await self.server.tasks.handle(self.ws, {"type":"task.catalog.update", "payload":{"catalog":self.catalog,"config":updated}}, set())
        self.ws.send_json = send
        task = await self.start()
        self.assertEqual(task["status"], "awaiting_approval", task["reason"])
        self.assertFalse(any(i >= 2 for i,_,_ in self.requests))
        self.assertEqual(task["resolved_roles"]["executor"]["_connection"]["connection_id"], "service-1")

    async def test_lan_ollama_is_local_and_credential_url_rejected(self):
        await self.setup_catalog()
        self.catalog["connections"][0]["base_url"] = "http://192.168.10.20:11434"
        resolved = self.server.tasks.catalog().resolve(self.cfg, self.catalog)
        self.assertEqual(resolved["roles"]["planner"]["route"], "local")
        self.catalog["connections"][0]["base_url"] = "https://user:password@example.test/v1"
        with self.assertRaisesRegex(ValueError, "embedded credentials"):
            validate_catalog(self.catalog)

    async def test_legacy_migration_idempotent_preserves_config_and_keys(self):
        original = self.config()
        self.server.store.set_setting("orchestration.config", json.dumps(original))
        self.server.openai_api_key = "legacy-secret"
        catalog = self.server.tasks.catalog()
        first = catalog.load()
        self.assertEqual(first, catalog.load())
        config = self.server.tasks.settings()
        self.assertTrue(all(p.get("model_profile_id") for p in config["roles"].values()))
        self.assertEqual(config["budget"], original["budget"])
        self.assertEqual(self.server.openai_api_key, "legacy-secret")
        self.assertNotIn("legacy-secret", json.dumps(first))
        api = next(c for c in first["connections"] if c["provider_type"] == "openai_compatible")
        self.assertEqual(api["credential_reference"], "legacy-openai")

    async def test_corrupt_migration_preserves_original(self):
        self.server.store.set_setting("orchestration.config", "{bad-json")
        with self.assertRaises(ValueError): self.server.tasks.catalog().load()
        self.assertEqual(self.server.store.get_setting("orchestration.config"), "{bad-json")
        self.assertIsNone(self.server.store.get_setting(KEY))

    async def test_invalid_and_disabled_binding_rejected_without_fallback(self):
        await self.setup_catalog()
        self.catalog["connections"][1]["enabled"] = False
        with self.assertRaisesRegex(ValueError, "disabled"):
            self.server.tasks.catalog().resolve(self.cfg, self.catalog)
        cfg = deepcopy(self.cfg)
        cfg["roles"]["executor"]["model_profile_id"] = "missing"
        with self.assertRaisesRegex(ValueError,"no longer exists"): self.server.tasks.catalog().resolve(cfg)

    async def test_local_only_rejects_explicit_remote_binding_before_request(self):
        await self.setup_catalog()
        self.cfg["strategy"] = "local-only"
        self.cfg["roles"]["planner"]["model_profile_id"] = "model-3"
        task = await self.start()
        self.assertEqual(task["status"], "paused")
        self.assertEqual(self.requests, [])

    async def test_unavailable_endpoint_pauses_without_paid_fallback(self):
        await self.setup_catalog()
        self.catalog["connections"][0]["base_url"] = "http://127.0.0.1:1"
        self.server.store.set_setting(KEY, json.dumps(self.catalog))
        task = await self.start()
        self.assertEqual(task["status"], "paused")
        self.assertFalse(self.requests)

    async def test_api_only_zero_budget_blocks_real_http(self):
        await self.setup_catalog()
        self.cfg["strategy"] = "api-only"
        self.cfg["budget"]["api_calls"] = 0
        for role in self.cfg["roles"]: self.cfg["roles"][role]["model_profile_id"] = "model-3"
        task = await self.start()
        self.assertEqual(task["status"], "paused")
        self.assertEqual(self.requests, [])

    async def test_api_only_actual_http_is_budgeted(self):
        await self.setup_catalog()
        cfg = deepcopy(self.cfg)
        cfg["strategy"] = "api-only"
        for binding in cfg["roles"].values(): binding["model_profile_id"] = "model-3"
        task = self.server.tasks.runtime.create(self.thread.id, "API-only text request", cfg, str(self.repo))
        guard = BudgetGuard(self.server.tasks.runtime, task["id"], cfg["budget"])
        async def notify(*args): pass
        router = ModelRouter(cfg, lambda route,p:self.server.tasks.make_provider({},route,p), guard, notify,
                             self.server.tasks.catalog().resolve(cfg)["roles"])
        await router.text("planner", [{"role":"user","content":"Diagnose only"}])
        self.assertEqual([i for i,_,_ in self.requests], [3])
        self.assertEqual(guard.runtime.usage(task["id"])["api_calls"], 1)

    async def test_migration_preserves_shared_model_role_limits_and_old_task(self):
        cfg = self.config()
        for role in ("planner","executor","reviewer"):
            cfg["roles"][role]["model"] = "shared-local"
        cfg["roles"]["executor"]["output_limit"] = 2048
        old_task = self.server.tasks.runtime.create(self.thread.id,"Old task",cfg,str(self.repo))
        catalog = self.server.tasks.catalog()
        self.server.store.set_setting("orchestration.config", json.dumps(cfg))
        catalog.load()
        migrated = catalog.resolve(self.server.tasks.settings())
        self.assertEqual(migrated["roles"]["planner"]["output_limit"],1024)
        self.assertEqual(migrated["roles"]["executor"]["output_limit"],2048)
        self.assertEqual(self.server.tasks.runtime.get(old_task["id"]),old_task)
