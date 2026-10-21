"""Durable autonomous execution metadata, anchored to existing TaskPlan IDs."""
from __future__ import annotations

import json
import time
import uuid
from typing import Any

ACTIVE = {"planning", "executing", "verifying", "repairing", "escalating"}
TRANSITIONS = {
    "pending": {"planning", "paused", "cancelled", "failed"},
    "planning": {"executing", "repairing", "escalating", "paused", "failed", "cancelled"},
    "executing": {"verifying", "repairing", "escalating", "paused", "failed", "cancelled"},
    "verifying": {"repairing", "awaiting_approval", "paused", "failed", "cancelled"},
    "repairing": {"planning", "executing", "escalating", "paused", "failed", "cancelled"},
    "escalating": {"repairing", "planning", "paused", "failed", "cancelled"},
    "awaiting_approval": {"completed", "paused", "verifying", "cancelled"},
    "paused": {"planning", "executing", "verifying", "cancelled"},
    "failed": {"paused", "cancelled"},
    "cancelled": {"paused"},
    "completed": {"paused"},
}


class TaskRuntimeStore:
    def __init__(self, plans):
        self.plans, self.db = plans, plans.db
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS autonomous_tasks (
                plan_id TEXT PRIMARY KEY REFERENCES task_plans(id) ON DELETE CASCADE,
                data_json TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS model_requests (
                id TEXT PRIMARY KEY,
                plan_id TEXT NOT NULL REFERENCES task_plans(id) ON DELETE CASCADE,
                route TEXT NOT NULL, role TEXT NOT NULL, model TEXT NOT NULL,
                reserved_tokens INTEGER NOT NULL, reserved_cost REAL NOT NULL,
                status TEXT NOT NULL, usage_json TEXT NOT NULL,
                created_at REAL NOT NULL
            );
        """)
        self.db.commit()

    def create(self, thread_id: str, goal: str, config: dict, source: str) -> dict:
        # Planner replaces this unstarted placeholder in the same plan.
        plan_id = self.plans.create(thread_id, goal, [{"description": "Generate structured task plan"}])
        value = {"id": plan_id, "thread_id": thread_id, "goal": goal,
                 "status": "pending", "config": config, "source": source,
                 "workspace": "", "branch": "", "planned": False,
                 "attempts": 0, "repairs": 0, "escalations": 0,
                 "elapsed_seconds": 0.0, "active_since": None,
                 "reason": "", "verification": [], "attempt_history": [], "report": {}}
        self.save(value)
        return value

    def save(self, value: dict) -> None:
        previous = self.db.execute("SELECT data_json FROM autonomous_tasks WHERE plan_id=?", (value["id"],)).fetchone()
        value["revision"] = (json.loads(previous[0]).get("revision", 0) if previous else 0) + 1
        with self.db:
            self.db.execute("INSERT INTO autonomous_tasks VALUES(?,?) ON CONFLICT(plan_id) "
                            "DO UPDATE SET data_json=excluded.data_json",
                            (value["id"], json.dumps(value, ensure_ascii=False, allow_nan=False)))

    def get(self, plan_id: str) -> dict:
        row = self.db.execute("SELECT data_json FROM autonomous_tasks WHERE plan_id=?", (plan_id,)).fetchone()
        if row is None:
            raise ValueError("Autonomous task not found")
        return json.loads(row[0])

    def list(self, thread_id: str) -> list[dict]:
        return [json.loads(row[0]) for row in self.db.execute(
            "SELECT a.data_json FROM autonomous_tasks a JOIN task_plans p ON p.id=a.plan_id "
            "WHERE p.thread_id=? ORDER BY p.updated_at DESC, p.rowid DESC", (thread_id,))]

    def transition(self, plan_id: str, status: str, reason: str = "", **updates) -> dict:
        task = self.get(plan_id)
        if status != task["status"] and status not in TRANSITIONS.get(task["status"], set()):
            raise ValueError(f"Illegal task transition: {task['status']} -> {status}")
        now = time.time()
        if task.get("active_since"):
            task["elapsed_seconds"] += max(0, now - task["active_since"])
        task.update(updates)
        task.update(status=status, reason=reason[:2000], active_since=now if status in ACTIVE else None)
        self.save(task)
        self.plans.checkpoint(plan_id, "task_" + status, blockers=[reason] if reason else [])
        return task

    def recover(self) -> None:
        ids = [row[0] for row in self.db.execute("SELECT plan_id FROM autonomous_tasks")]
        for plan_id in ids:
            if self.get(plan_id)["status"] in ACTIVE:
                self.transition(plan_id, "paused", "Agent restarted; review workspace before resuming. Uncertain API reservations retained.")

    def replace_unstarted_steps(self, plan_id: str, steps: list[dict]) -> None:
        # Validate through the existing plan contract before changing anything.
        if not 1 <= len(steps) <= 30 or any(
            not isinstance(s, dict) or not isinstance(s.get("description"), str)
            or not 1 <= len(s["description"].strip()) <= 4000
            or not isinstance(s.get("verification", ""), str) for s in steps
        ):
            raise ValueError("Planner must return 1..30 structured steps")
        with self.db:
            if self.db.execute("SELECT 1 FROM task_plan_executions WHERE plan_id=?", (plan_id,)).fetchone():
                raise ValueError("Cannot replace a plan with runtime evidence")
            self.db.execute("DELETE FROM task_plan_steps WHERE plan_id=?", (plan_id,))
            for position, step in enumerate(steps):
                self.db.execute("INSERT INTO task_plan_steps(id,plan_id,position,description,verification) VALUES(?,?,?,?,?)",
                                (str(uuid.uuid4()), plan_id, position, step["description"], step.get("verification", "")[:2000]))

    def append_repair_step(self, plan_id: str) -> None:
        steps = self.plans.get(plan_id)["steps"]
        if any(s["state"] not in {"completed", "skipped"} for s in steps):
            return
        with self.db:
            self.db.execute("INSERT INTO task_plan_steps(id,plan_id,position,description) VALUES(?,?,?,?)",
                            (str(uuid.uuid4()), plan_id, len(steps), "Repair the latest independent verification failure; inspect current files before changing them"))

    def usage(self, plan_id: str | None = None) -> dict[str, Any]:
        rows = self.db.execute("SELECT * FROM model_requests" + (" WHERE plan_id=?" if plan_id else ""),
                               (plan_id,) if plan_id else ()).fetchall()
        api = [r for r in rows if r["route"] == "api"]
        usage = [json.loads(r["usage_json"]) for r in api]
        return {"api_calls": len(api), "local_calls": len(rows) - len(api),
                "reserved_tokens": sum(r["reserved_tokens"] for r in api),
                "reserved_cost": sum(r["reserved_cost"] for r in api),
                "input_tokens": sum(u.get("input_tokens", 0) or 0 for u in usage),
                "output_tokens": sum(u.get("output_tokens", 0) or 0 for u in usage),
                "cached_tokens": sum(u.get("cached_tokens", 0) or 0 for u in usage),
                "actual_cost": sum(u.get("actual_cost", 0) or 0 for u in usage),
                "actual_cost_known": bool(api) and all(u.get("actual_cost") is not None for u in usage),
                "estimated": any(u.get("estimated", True) for u in usage),
                "precision": "Conservative reservation; provider tokenizer/billing may differ. Unknown requests retain full reservation."}
