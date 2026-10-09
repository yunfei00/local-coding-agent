import os
import sqlite3
import tempfile
import unittest

from agent.task_plans import TaskPlanStore


class TaskPlanStoreTests(unittest.TestCase):
    def test_restart_and_evidence_gate(self):
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, "state.db")
            db = sqlite3.connect(path)
            store = TaskPlanStore(db)
            plan_id = store.create("thread-1", "Fix failing tests", [
                {"description": "Run tests", "verification": "test output"},
                {"description": "Apply fix"},
            ])
            step_id = store.get(plan_id)["steps"][0]["id"]
            with self.assertRaises(ValueError):
                store.update_step(plan_id, step_id, "completed")
            store.update_step(plan_id, step_id, "completed",
                              [{"tool": "test", "exit_code": 0}])
            store.checkpoint(plan_id, "milestone", commands_run=[{"exit_code": 0}])
            db.close()
            restored = TaskPlanStore(sqlite3.connect(path)).resumable(plan_id)
            self.assertEqual(restored["plan"]["steps"][0]["state"], "completed")
            self.assertEqual(restored["checkpoint"]["reason"], "milestone")
            self.assertEqual(len(restored["checkpoint"]["snapshot"]["commands_run"]), 1)

    def test_thread_isolation_and_invalid_state(self):
        store = TaskPlanStore(sqlite3.connect(":memory:"))
        a = store.create("a", "Goal A", [{"description": "step"}])
        store.create("b", "Goal B", [{"description": "step"}])
        self.assertEqual(len(store.list_for_thread("a")), 1)
        step = store.get(a)["steps"][0]["id"]
        with self.assertRaises(ValueError):
            store.update_step(a, step, "made_up")


if __name__ == "__main__":
    unittest.main()
