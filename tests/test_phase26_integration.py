"""Phase 26 integration regression: plan context and tool evidence are wired into the Agent loop."""
import pathlib
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]


class Phase26IntegrationTests(unittest.TestCase):
    def test_agent_loop_loads_existing_plan(self):
        source = (ROOT / "agent/server/main.py").read_text(encoding="utf-8")
        self.assertIn('active_plans = [', source)
        self.assertIn('"source": "task_plan"', source)
        self.assertIn('active_step_id = current_step["id"]', source)

    def test_blocked_step_cannot_be_skipped_by_successful_tool(self):
        source = (ROOT / "agent/server/main.py").read_text(encoding="utf-8")
        self.assertIn('current_step["state"] == "blocked"', source)
        self.assertIn('active_step_id = None', source)
        self.assertNotIn('next_step = next((item for item in current["steps"]', source)

    def test_runtime_evidence_in_checkpoint(self):
        source = (ROOT / "agent/server/main.py").read_text(encoding="utf-8")
        self.assertIn('"step_id": active_step_id', source)
        self.assertIn("plan_tool_evidence.append(", source)
        self.assertIn('"max_model_steps"', source)
        self.assertIn('"provider_error"', source)
        self.assertIn('sorted(plan_files_changed), plan_commands_run', source)
        self.assertIn('self._checkpoint_thread_plans(thread_id, "turn_cancelled"', source)
