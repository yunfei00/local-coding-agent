"""Actual Agent/tool execution for v0.3 plans, recovery, metrics and safety."""
import asyncio
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from agent.permissions.policy import PermissionMode
from agent.server.main import AgentServer
from agent.task_plans import automatic_steps
from test_agent_reliability import (BlockingProvider, FakeWebSocket, RetryThenPatchProvider,
                                    ScriptedProvider, final_step, tool_step)


class V03RuntimeTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.data = tempfile.TemporaryDirectory()
        self.repo = tempfile.TemporaryDirectory()
        self.env = patch.dict(os.environ, {"LCA_DATA_DIR": self.data.name})
        self.env.start()
        self.server = AgentServer("test-token")
        self.project, self.thread, _ = self.server.projects.open(self.repo.name, active_model="fake-model")
        self.ws = FakeWebSocket()

    async def asyncTearDown(self):
        await self.server.close_async()
        self.server.close()
        self.env.stop()
        self.repo.cleanup()
        self.data.cleanup()

    async def run_turn(self, steps, turn="runtime", prompt="Inspect this workspace"):
        self.server.provider = ScriptedProvider(steps)
        await self.server.run_tool_turn(self.ws, thread_id=self.thread.id, turn_id=turn,
                                        prompt=prompt, model="fake-model")

    def plan(self, steps):
        return self.server.store.task_plans.create(self.thread.id, "Repair calculator", steps)

    async def test_metrics_include_retry_real_tools_and_context(self):
        Path(self.repo.name, "value.txt").write_text("before", encoding="utf-8")
        self.server.provider = RetryThenPatchProvider()
        await self.server.run_tool_turn(self.ws, thread_id=self.thread.id, turn_id="retry",
                                        prompt="Fix value.txt", model="fake-model")
        trace = next(e for e in self.ws.messages if e["type"] == "turn.metrics")["payload"]
        summary = trace["execution_summary"]
        self.assertEqual(summary["provider_retries"], 1)
        self.assertEqual(summary["model_steps"], 2)
        self.assertEqual(summary["tool_calls"], 1)
        self.assertEqual(summary["tool_failures"], 0)
        usage = [e["payload"] for e in self.ws.messages if e["type"] == "context.updated"][-1]
        self.assertEqual(summary["context_token_estimate"], usage["estimated_input_tokens"])
        self.assertEqual(summary["context_sources"], usage["context_sources"])
        self.assertNotIn("before", json.dumps(trace))

    async def test_failed_validation_blocks_plan_with_persisted_failure(self):
        plan = self.plan([{"description": "Run failing validation", "verification": "tests pass"}])
        await self.run_turn([tool_step("run_command", {"command": "python -c \"raise SystemExit(1)\""}), final_step()])
        plans = self.server.store.task_plans
        self.assertEqual(plans.active_step(plan)["state"], "blocked")
        row = self.server.store.connection.execute("SELECT * FROM task_plan_executions").fetchone()
        self.assertEqual(row["status"], "failed")
        self.assertEqual(row["exit_code"], 1)
        with self.assertRaises(ValueError):
            plans.execution_evidence(plan, row["step_id"], [row["call_id"]])

    async def test_fixed_fixture_is_repaired_by_real_tools_in_plan_order(self):
        fixture = Path(__file__).resolve().parents[1] / "manual-fixtures/phase26-task-plan"
        shutil.copytree(fixture / "src", Path(self.repo.name, "src"))
        shutil.copytree(fixture / "tests", Path(self.repo.name, "tests"))
        for args in (["init", "-q"], ["config", "user.name", "CI"], ["config", "user.email", "ci@example.test"],
                     ["add", "."], ["commit", "-qm", "fixture"]):
            subprocess.run(["git", *args], cwd=self.repo.name, check=True, capture_output=True)
        plan = self.plan([{"description": "Read calculator"}, {"description": "Fix addition"},
                          {"description": "Test and review", "verification": "unittest passes"}])
        await self.run_turn([
            tool_step("read_file", {"path": "src/calculator.py"}), final_step("inspected"),
            tool_step("apply_patch", {"path": "src/calculator.py", "old_text": "return a - b", "new_text": "return a + b"}),
            final_step("fixed"),
            tool_step("run_command", {"command": "python -m unittest discover -s tests -v"}),
            tool_step("git_diff", {}), final_step("verified"),
        ])
        state = self.server.store.task_plans.get(plan)
        self.assertTrue(all(s["state"] == "completed" for s in state["steps"]), state)
        self.assertTrue(all(s["evidence"][0]["tool_call_id"] for s in state["steps"]))
        self.assertEqual(self.server.store.task_plans.latest_checkpoint(plan)["reason"], "plan_completed")
        self.assertIn("return a + b", Path(self.repo.name, "src/calculator.py").read_text())
        count = subprocess.check_output(["git", "rev-list", "--count", "HEAD"], cwd=self.repo.name, text=True)
        self.assertEqual(count.strip(), "1")

    async def test_notes_and_foreign_call_ids_cannot_complete_step(self):
        plan = self.plan([{"description": "Read file"}])
        step = self.server.store.task_plans.active_step(plan)["id"]
        await self.server.handle_message(self.ws, {"type": "plan.step.update", "payload": {
            "thread_id": self.thread.id, "plan_id": plan, "step_id": step, "state": "completed",
            "evidence": [{"note": "I say it passed"}], "tool_call_ids": ["invented"]}}, set())
        self.assertEqual(self.ws.messages[-1]["payload"]["code"], "PLAN_INVALID")
        self.assertEqual(self.server.store.task_plans.active_step(plan)["state"], "pending")

    async def test_stop_restart_requires_confirmation_and_preserves_completed_step(self):
        Path(self.repo.name, "file.txt").write_text("hello", encoding="utf-8")
        plan = self.plan([{"description": "Read file"}, {"description": "Continue inspection"}])
        await self.run_turn([tool_step("read_file", {"path": "file.txt"}), final_step(), final_step()])
        # The first step completed; the second has no evidence and stays pending.
        plans = self.server.store.task_plans
        step = plans.active_step(plan)["id"]
        plans.update_step(plan, step, "in_progress")
        provider = BlockingProvider()
        self.server.provider = provider
        task = asyncio.create_task(self.server.run_tool_turn(self.ws, thread_id=self.thread.id,
            turn_id="cancel", prompt="Continue inspection", model="fake-model"))
        await asyncio.wait_for(provider.started.wait(), 5)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertEqual(plans.latest_checkpoint(plan)["reason"], "turn_cancelled")
        await self.server.close_async()
        self.server.close()
        self.server = AgentServer("test-token")
        self.project, self.thread, _ = self.server.projects.open(self.repo.name, active_model="fake-model")
        restored = self.server.store.task_plans.get(plan)
        self.assertEqual(restored["steps"][0]["state"], "completed")
        self.assertEqual(restored["steps"][1]["id"], step)
        await self.server.handle_message(self.ws, {"type": "turn.start", "payload": {
            "thread_id": self.thread.id, "prompt": "Continue"}}, set())
        self.assertEqual(self.ws.messages[-1]["payload"]["code"], "PLAN_RESUME_CONFIRMATION_REQUIRED")

    async def test_plan_does_not_bypass_read_only_permission(self):
        plan = self.plan([{"description": "Write file"}])
        self.server.permissions.set_mode(PermissionMode.READ_ONLY)
        await self.run_turn([tool_step("write_file", {"path": "forbidden.txt", "content": "bad"}), final_step()])
        self.assertFalse(Path(self.repo.name, "forbidden.txt").exists())
        self.assertEqual(self.server.store.task_plans.active_step(plan)["state"], "blocked")
        metrics = self.server.last_turn_trace["execution_summary"]
        self.assertEqual(metrics["tool_failures"], 1)

    def test_auto_plans_are_reserved_for_complex_requests(self):
        self.assertEqual(automatic_steps("你好，读取 README"), [])
        self.assertEqual(len(automatic_steps("1. 检查代码\n2. 实现修复\n3. 运行测试")), 3)

    async def test_persisted_mutation_is_not_replayed_in_later_step(self):
        plan = self.plan([{"description": "Write value"}, {"description": "Inspect the result"}])
        write = tool_step("write_file", {"path": "once.txt", "content": "written once"})
        await self.run_turn([write, final_step(), write, final_step()])
        steps = self.server.store.task_plans.get(plan)["steps"]
        self.assertEqual(steps[0]["state"], "completed")
        self.assertEqual(steps[1]["state"], "blocked")
        results = [e["payload"]["result"] for e in self.ws.messages if e["type"] == "tool.completed"]
        self.assertEqual(results[-1]["error"]["code"], "PLAN_OPERATION_ALREADY_APPLIED")
        self.assertEqual(Path(self.repo.name, "once.txt").read_text(), "written once")

    async def test_crash_without_checkpoint_still_requires_confirmation(self):
        plan = self.plan([{"description": "Unknown interrupted write"}])
        step = self.server.store.task_plans.active_step(plan)["id"]
        self.server.store.task_plans.update_step(plan, step, "in_progress")
        self.server.store.task_plans.record_execution(plan, step, "crashed-call", "crashed-turn", "write_file")
        self.assertIsNone(self.server.store.task_plans.latest_checkpoint(plan))
        await self.server.handle_message(self.ws, {"type": "turn.start", "payload": {
            "thread_id": self.thread.id, "prompt": "Continue"}}, set())
        self.assertEqual(self.ws.messages[-1]["payload"]["code"], "PLAN_RESUME_CONFIRMATION_REQUIRED")
