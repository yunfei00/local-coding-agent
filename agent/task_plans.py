"""Persistent, thread-scoped task plans and evidence-backed checkpoints.

This module intentionally has no UI or Agent-loop dependency. A caller may
create plans for long-running work; simple requests need not create a plan.
"""
from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timezone
from typing import Any

STATES = frozenset({"pending", "in_progress", "completed", "skipped", "blocked"})
MAX_STEPS = 100


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class TaskPlanStore:
    def __init__(self, connection: sqlite3.Connection):
        self.db = connection
        self.db.execute("PRAGMA foreign_keys=ON")
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS task_plans (
                id TEXT PRIMARY KEY,
                thread_id TEXT NOT NULL,
                goal TEXT NOT NULL,
                current_step_id TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_task_plans_thread
                ON task_plans(thread_id, updated_at);
            CREATE TABLE IF NOT EXISTS task_plan_steps (
                id TEXT PRIMARY KEY,
                plan_id TEXT NOT NULL REFERENCES task_plans(id) ON DELETE CASCADE,
                position INTEGER NOT NULL,
                description TEXT NOT NULL,
                verification TEXT NOT NULL DEFAULT '',
                state TEXT NOT NULL DEFAULT 'pending',
                evidence_json TEXT NOT NULL DEFAULT '[]',
                UNIQUE(plan_id, position)
            );
            CREATE TABLE IF NOT EXISTS task_checkpoints (
                id TEXT PRIMARY KEY,
                plan_id TEXT NOT NULL REFERENCES task_plans(id) ON DELETE CASCADE,
                created_at TEXT NOT NULL,
                reason TEXT NOT NULL,
                snapshot_json TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_task_checkpoints_plan
                ON task_checkpoints(plan_id, created_at);
        """)
        self.db.commit()

    def create(self, thread_id: str, goal: str, steps: list[dict[str, str]]) -> str:
        if not thread_id.strip() or not goal.strip() or not 1 <= len(steps) <= MAX_STEPS:
            raise ValueError("thread, goal and 1..100 steps required")
        if any(not s.get("description", "").strip() for s in steps):
            raise ValueError("step description required")
        plan_id, now = str(uuid.uuid4()), _now()
        with self.db:
            self.db.execute(
                "INSERT INTO task_plans(id,thread_id,goal,created_at,updated_at) VALUES(?,?,?,?,?)",
                (plan_id, thread_id, goal, now, now),
            )
            for i, step in enumerate(steps):
                self.db.execute(
                    "INSERT INTO task_plan_steps(id,plan_id,position,description,verification) VALUES(?,?,?,?,?)",
                    (str(uuid.uuid4()), plan_id, i, step["description"], step.get("verification", "")),
                )
        return plan_id

    def get(self, plan_id: str) -> dict[str, Any]:
        self.db.row_factory = sqlite3.Row
        plan = self.db.execute("SELECT * FROM task_plans WHERE id=?", (plan_id,)).fetchone()
        if plan is None:
            raise KeyError(plan_id)
        steps = self.db.execute(
            "SELECT * FROM task_plan_steps WHERE plan_id=? ORDER BY position", (plan_id,)
        ).fetchall()
        return {
            **dict(plan),
            "steps": [
                {**dict(s), "evidence": json.loads(s["evidence_json"])}
                for s in steps
            ],
        }

    def list_for_thread(self, thread_id: str) -> list[dict[str, Any]]:
        ids = self.db.execute(
            "SELECT id FROM task_plans WHERE thread_id=? ORDER BY updated_at DESC",
            (thread_id,),
        ).fetchall()
        return [self.get(row[0]) for row in ids]

    def update_step(self, plan_id: str, step_id: str, state: str,
                    evidence: list[dict[str, Any]] | None = None) -> None:
        if state not in STATES:
            raise ValueError("invalid step state")
        if state == "completed" and not evidence:
            raise ValueError("completion requires runtime evidence")
        with self.db:
            result = self.db.execute(
                "UPDATE task_plan_steps SET state=?,evidence_json=? WHERE id=? AND plan_id=?",
                (state, json.dumps(evidence or []), step_id, plan_id),
            )
            if result.rowcount != 1:
                raise KeyError(step_id)
            self.db.execute(
                "UPDATE task_plans SET current_step_id=?,updated_at=? WHERE id=?",
                (step_id if state == "in_progress" else None, _now(), plan_id),
            )

    def checkpoint(self, plan_id: str, reason: str,
                   files_changed: list[str] | None = None,
                   commands_run: list[dict[str, Any]] | None = None,
                   git_status: str = "",
                   blockers: list[str] | None = None) -> str:
        plan = self.get(plan_id)
        checkpoint_id = str(uuid.uuid4())
        snapshot = {
            "plan": plan,
            "files_changed": files_changed or [],
            "commands_run": commands_run or [],
            "git_status": git_status,
            "blockers": blockers or [],
        }
        with self.db:
            self.db.execute(
                "INSERT INTO task_checkpoints(id,plan_id,created_at,reason,snapshot_json) VALUES(?,?,?,?,?)",
                (checkpoint_id, plan_id, _now(), reason, json.dumps(snapshot)),
            )
        return checkpoint_id

    def latest_checkpoint(self, plan_id: str) -> dict[str, Any] | None:
        row = self.db.execute(
            "SELECT id,created_at,reason,snapshot_json FROM task_checkpoints "
            "WHERE plan_id=? ORDER BY rowid DESC LIMIT 1", (plan_id,),
        ).fetchone()
        if row is None:
            return None
        return {"id": row[0], "created_at": row[1],
                "reason": row[2], "snapshot": json.loads(row[3])}

    def resumable(self, plan_id: str) -> dict[str, Any]:
        """Return persisted state; never automatically replay mutating tools."""
        return {"plan": self.get(plan_id), "checkpoint": self.latest_checkpoint(plan_id)}
