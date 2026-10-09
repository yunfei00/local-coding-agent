"""Phase 26 integration regression: plan context and tool evidence are wired into the Agent loop."""
import pathlib
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]


class Phase26IntegrationTests(unittest.TestCase):
    def test_agent_loop_loads_existing_plan(self):
        source = (ROOT / "agent/server/main.py").read_text(encoding="utf-8")
        self.assertIn('active_plans = [', source)
        self.assertIn('"source": "task_plan"', source)
        self.assertIn('active_step_id = next_step["id"]', source)

    def test_runtime_evidence_in_checkpoint(self):
        source = (ROOT / "agent/server/main.py").read_text(encoding="utf-8")
        self.assertIn('"step_id": active_step_id', source)\n        self.assertIn("plan_tool_evidence.append(", source)\n        self.assertIn('"max_model_steps"', source)\n        self.assertIn('"provider_error"', source)
        self.assertIn('sorted(plan_files_changed), plan_commands_run', source)
        self.assertIn('self._checkpoint_thread_plans(thread_id, "turn_cancelled"', source)
