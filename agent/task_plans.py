"""Persistent, thread-scoped task plans and evidence-backed checkpoints.

This module intentionally has no UI or Agent-loop dependency. A caller may
create plans for long-running work; simple requests need not create a plan.
"""
from __future__ import annotations

import json
import sqlite3
import uuid
import re
import hashlib
from datetime import datetime, timezone
from typing import Any

STATES = frozenset({"pending", "in_progress", "completed", "skipped", "blocked"})
MAX_STEPS = 100


def automatic_steps(prompt: str) -> list[dict[str, str]]:
    """Plan explicit multi-step work; ordinary chat and small tasks stay plan-free."""
    lines = [re.sub(r"^\s*(?:\d+[.)、]|[-*])\s*", "", line).strip()
             for line in prompt.splitlines() if re.match(r"^\s*(?:\d+[.)、]|[-*])\s*\S", line)]
    if len(lines) >= 3:
        return [{"description": line[:1000]} for line in lines[:MAX_STEPS]]
    actions = re.findall(r"修复|重构|实现|测试|验证|检查|implement|refactor|verify|test|review", prompt, re.I)
    if len(prompt) >= 180 and len(set(actions)) >= 3:
        return [{"description": "Inspect the project and identify the requested changes"},
                {"description": "Implement the requested changes"},
                {"description": "Run relevant tests and inspect the final diff", "verification": "Successful validation command"}]
    return []


def mutation_fingerprint(tool: str, arguments: dict[str, Any], read_only: bool = False) -> str:
    # Process handles expire at scope cleanup; starting a new process after an
    # explicit task resume is not replaying a completed file mutation.
    if read_only or tool.startswith('desktop_') or tool in {"start_process", "read_process", "stop_process"}:
        return ""
    if tool == "run_command" and re.match(r"^(?:uv\s+run\s+)?(?:python(?:3)?\s+-m\s+(?:unittest|pytest|compileall)\b|npm(?:\.cmd)?\s+(?:run\s+)?(?:test|typecheck|build)\b)", str(arguments.get("command", "")).strip(), re.I):
        return ""
    return hashlib.sha256((tool + json.dumps(arguments, sort_keys=True, ensure_ascii=False)).encode()).hexdigest()


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
            CREATE TABLE IF NOT EXISTS task_plan_executions (
                call_id TEXT PRIMARY KEY,
                plan_id TEXT NOT NULL REFERENCES task_plans(id) ON DELETE CASCADE,
                step_id TEXT NOT NULL,
                turn_id TEXT NOT NULL,
                tool TEXT NOT NULL,
                status TEXT NOT NULL,
                exit_code INTEGER,
                changed_paths TEXT NOT NULL DEFAULT '[]',
                fingerprint TEXT NOT NULL DEFAULT ''
            );
        """)
        if "fingerprint" not in {row[1] for row in self.db.execute("PRAGMA table_info(task_plan_executions)")}:
            self.db.execute("ALTER TABLE task_plan_executions ADD COLUMN fingerprint TEXT NOT NULL DEFAULT ''")
        if "metadata_json" not in {row[1] for row in self.db.execute("PRAGMA table_info(task_plan_executions)")}:
            self.db.execute("ALTER TABLE task_plan_executions ADD COLUMN metadata_json TEXT NOT NULL DEFAULT '{}'")
        self.db.commit()

    def record_execution(self, plan_id: str, step_id: str, call_id: str, turn_id: str,
                         tool: str, result: dict[str, Any] | None = None, fingerprint: str = "") -> None:
        """Store only execution metadata, never arguments, output, or model reasoning."""
        with self.db:
            data = (result or {}).get("data") or {}
            metadata = {k: data[k] for k in ("process_id", "pid", "shell", "state", "log_path", "metadata_path", "log_truncated", "artifact_id", "path", "width", "height", "dpi", "vision_feedback", "window_id", "window_generation", "sha256", "captured_at") if k in data}
            if result:
                metadata.update(duration_ms=result.get("duration_ms"), error_code=(result.get("error") or {}).get("code") or data.get("error_code"))
            self.db.execute(
                "INSERT INTO task_plan_executions(call_id,plan_id,step_id,turn_id,tool,status,exit_code,changed_paths,fingerprint,metadata_json) VALUES(?,?,?,?,?,?,?,?,?,?) "
                "ON CONFLICT(call_id) DO UPDATE SET status=excluded.status,exit_code=excluded.exit_code,changed_paths=excluded.changed_paths,metadata_json=excluded.metadata_json",
                (call_id, plan_id, step_id, turn_id, tool,
                 "running" if result is None else "succeeded" if result.get("ok") else "failed",
                 result.get("exit_code") if result else None,
                 json.dumps(list((result or {}).get("changed_paths") or [])[:100]), fingerprint, json.dumps(metadata)),
            )

    def executions(self, plan_id):
        return [{"call_id": r["call_id"], "tool": r["tool"], "status": r["status"], "exit_code": r["exit_code"],
                 "metadata": json.loads(r["metadata_json"])} for r in self.db.execute(
                     "SELECT * FROM task_plan_executions WHERE plan_id=? ORDER BY rowid", (plan_id,))]

    def previously_applied(self, plan_id: str, fingerprint: str) -> bool:
        return bool(fingerprint and self.db.execute(
            "SELECT 1 FROM task_plan_executions WHERE plan_id=? AND fingerprint=? AND status='succeeded' LIMIT 1",
            (plan_id, fingerprint)).fetchone())

    def execution_evidence(self, plan_id: str, step_id: str,
                           call_ids: list[str]) -> list[dict[str, Any]]:
        if not call_ids or len(call_ids) > 100:
            raise ValueError("Provide 1..100 actual tool call IDs for this step")
        evidence = []
        for call_id in call_ids:
            row = self.db.execute(
                "SELECT * FROM task_plan_executions WHERE call_id=? AND plan_id=? AND step_id=?",
                (call_id, plan_id, step_id),
            ).fetchone()
            if row is None or row["status"] != "succeeded" or row["exit_code"] not in (None, 0):
                raise ValueError("Completion requires successful persisted tool evidence for this step")
            evidence.append({"tool_call_id": row["call_id"], "step_id": step_id,
                             "tool": row["tool"], "ok": True, "exit_code": row["exit_code"]})
        return evidence

    def create(self, thread_id: str, goal: str, steps: list[dict[str, str]]) -> str:
        if not thread_id.strip() or not goal.strip() or not 1 <= len(steps) <= MAX_STEPS:
            raise ValueError("thread, goal and 1..100 steps required")
        if any(not isinstance(s, dict) or not isinstance(s.get("description"), str)
               or not s["description"].strip() or len(s["description"]) > 4000
               or not isinstance(s.get("verification", ""), str) for s in steps):
            raise ValueError("Each step requires a nonempty description of at most 4000 characters")
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
        executions = [dict(row) for row in self.db.execute(
            "SELECT call_id,step_id,tool,status,exit_code FROM task_plan_executions WHERE plan_id=? ORDER BY rowid DESC LIMIT 100", (plan_id,))]
        return {
            **dict(plan),
            "steps": [
                {**dict(s), "evidence": json.loads(s["evidence_json"]),
                 "executions": [item for item in executions if item["step_id"] == s["id"]]}
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


    def edit_step(self, plan_id: str, step_id: str, description: str,
                  verification: str = "") -> None:
        """Edit a pending step without invalidating recorded execution evidence."""
        if not description.strip():
            raise ValueError("step description required")
        with self.db:
            changed = self.db.execute(
                "UPDATE task_plan_steps SET description=?,verification=? "
                "WHERE plan_id=? AND id=? AND state='pending'",
                (description, verification, plan_id, step_id),
            )
            if changed.rowcount != 1:
                raise ValueError("only pending steps can be edited")
            self.db.execute("UPDATE task_plans SET updated_at=? WHERE id=?",
                            (_now(), plan_id))

    def reorder_steps(self, plan_id: str, step_ids: list[str]) -> None:
        """Reorder only unstarted steps; completed evidence remains anchored."""
        steps = self.get(plan_id)["steps"]
        if len(step_ids) != len(steps) or set(step_ids) != {s["id"] for s in steps}:
            raise ValueError("step ids must be an exact permutation")
        original_fixed = {s["position"]: s["id"] for s in steps
                          if s["state"] != "pending"}
        if any(step_ids[position] != step_id
               for position, step_id in original_fixed.items()):
            raise ValueError("cannot move a started or finished step")
        with self.db:
            # UNIQUE(plan_id,position) requires a collision-free temporary range.
            offset = len(steps)
            for position, step_id in enumerate(step_ids):
                self.db.execute(
                    "UPDATE task_plan_steps SET position=? WHERE plan_id=? AND id=?",
                    (position + offset, plan_id, step_id),
                )
            for position, step_id in enumerate(step_ids):
                self.db.execute(
                    "UPDATE task_plan_steps SET position=? WHERE plan_id=? AND id=?",
                    (position, plan_id, step_id),
                )
            self.db.execute("UPDATE task_plans SET updated_at=? WHERE id=?",
                            (_now(), plan_id))

    def interrupt(self, plan_id: str, reason: str = "interrupted") -> str:
        """Save a resumable snapshot without replaying any command."""
        return self.checkpoint(plan_id, reason)

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
            self.db.execute("DELETE FROM task_checkpoints WHERE plan_id=? AND id NOT IN "
                            "(SELECT id FROM task_checkpoints WHERE plan_id=? ORDER BY rowid DESC LIMIT 50)",
                            (plan_id, plan_id))
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

    def active_step(self, plan_id: str) -> dict[str, Any] | None:
        """Return first unfinished step in plan order."""
        return next((step for step in self.get(plan_id)["steps"]
                     if step["state"] not in ("completed", "skipped")), None)

    def advance_verified(self, plan_id: str, step_id: str,
                         evidence: list[dict[str, Any]],
                         verification_passed: bool) -> bool:
        """Only complete the first unfinished, unblocked step with tool evidence."""
        current = self.active_step(plan_id)
        if not current or current["id"] != step_id or current["state"] == "blocked":
            return False
        if not verification_passed or not evidence:
            return False
        if not all(item.get("ok") is True for item in evidence):
            return False
        self.update_step(plan_id, step_id, "completed", evidence)
        return True

    def prepare_resume(self, plan_id: str) -> dict[str, Any]:
        """Explicit, non-executing resume: identify the first unfinished step.

        Completed and skipped steps are never reset or replayed. A previously
        in-progress step is left intact until the user verifies the workspace.
        """
        plan = self.get(plan_id)
        checkpoint = self.latest_checkpoint(plan_id)
        next_step = next(
            (step for step in plan["steps"] if step["state"] not in ("completed", "skipped")),
            None,
        )
        return {
            "plan": plan,
            "checkpoint": checkpoint,
            "next_step": next_step,
            "requires_workspace_verification": next_step is not None,
            "automatic_replay": False,
        }

    def resumable(self, plan_id: str) -> dict[str, Any]:
        """Return persisted state; never automatically replay mutating tools."""
        return {"plan": self.get(plan_id), "checkpoint": self.latest_checkpoint(plan_id)}
