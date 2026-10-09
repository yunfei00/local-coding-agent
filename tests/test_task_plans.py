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
            restored_db = sqlite3.connect(path)
            restored = TaskPlanStore(restored_db).resumable(plan_id)
            self.assertEqual(restored["plan"]["steps"][0]["state"], "completed")
            self.assertEqual(restored["checkpoint"]["reason"], "milestone")
            self.assertEqual(len(restored["checkpoint"]["snapshot"]["commands_run"]), 1)
            restored_db.close()

    def test_edit_reorder_and_interrupt(self):
        store = TaskPlanStore(sqlite3.connect(":memory:"))
        plan = store.create("t", "goal", [
            {"description": "first"}, {"description": "second"},
            {"description": "third"}])
        steps = store.get(plan)["steps"]
        ids = [step["id"] for step in steps]
        store.edit_step(plan, ids[1], "edited", "test passes")
        store.reorder_steps(plan, [ids[0], ids[2], ids[1]])
        self.assertEqual(store.get(plan)["steps"][1]["id"], ids[2])
        store.update_step(plan, ids[0], "completed", [{"tool": "test", "exit_code": 0}])
        with self.assertRaises(ValueError):
            store.reorder_steps(plan, [ids[2], ids[0], ids[1]])
        with self.assertRaises(ValueError):
            store.edit_step(plan, ids[0], "rewrite completed step")
        store.interrupt(plan)
        self.assertEqual(store.resumable(plan)["checkpoint"]["reason"], "interrupted")

    def test_safe_resume_never_replays_completed_steps(self):
        store = TaskPlanStore(sqlite3.connect(":memory:"))
        plan = store.create("t", "repair", [
            {"description": "inspect"}, {"description": "fix"}, {"description": "verify"}])
        steps = store.get(plan)["steps"]
        store.update_step(plan, steps[0]["id"], "completed",
                          [{"tool": "read_file", "ok": True}])
        store.update_step(plan, steps[1]["id"], "in_progress")
        store.checkpoint(plan, "turn_cancelled",
                         files_changed=["src/calculator.py"],
                         commands_run=[{"tool": "write_file", "ok": True}])
        resume = store.prepare_resume(plan)
        self.assertEqual(resume["next_step"]["id"], steps[1]["id"])
        self.assertEqual(resume["plan"]["steps"][0]["state"], "completed")
        self.assertEqual(resume["checkpoint"]["snapshot"]["files_changed"],
                         ["src/calculator.py"])
        self.assertTrue(resume["requires_workspace_verification"])
        self.assertFalse(resume["automatic_replay"])
        self.assertEqual(store.get(plan)["steps"][1]["state"], "in_progress")

    def test_ordered_evidence_and_blocked_step(self):
        store = TaskPlanStore(sqlite3.connect(":memory:"))
        plan = store.create("t", "goal", [
            {"description": "first"}, {"description": "second"}])
        first, second = [step["id"] for step in store.get(plan)["steps"]]
        evidence = [{"tool": "read_file", "ok": True}]
        self.assertFalse(store.advance_verified(plan, second, evidence, True))
        self.assertFalse(store.advance_verified(plan, first, evidence, False))
        self.assertFalse(store.advance_verified(
            plan, first, [{"tool": "shell", "ok": False}], True))
        self.assertTrue(store.advance_verified(plan, first, evidence, True))
        self.assertEqual(store.active_step(plan)["id"], second)
        store.update_step(plan, second, "blocked")
        self.assertFalse(store.advance_verified(plan, second, evidence, True))
        store.update_step(plan, second, "in_progress")
        self.assertTrue(store.advance_verified(plan, second, evidence, True))
        self.assertIsNone(store.active_step(plan))

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
