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
from contextlib import nullcontext
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
    if read_only or tool in {'desktop_list_windows','desktop_screenshot','desktop_inspect','desktop_wait','desktop_focus_window',"read_process", "stop_process"}:
        return ""
    return hashlib.sha256((tool + json.dumps(arguments, sort_keys=True, ensure_ascii=False)).encode()).hexdigest()


def repeatable_check(tool: str, arguments: dict[str, Any]) -> bool:
    """Only plain validation invocations may repeat after a successful checkpoint.

    Compound shells and arbitrary scripts remain protected mutations, even if
    they start with a test command. Interrupted checks still require approval.
    """
    command = str(arguments.get('command','')).strip()
    if tool=='run_command' and '&&' in command:
        parts=command.split('&&')
        return 2<=len(parts)<=6 and all(repeatable_check(tool,{'command':part.strip()}) for part in parts)
    if tool != 'run_command' or re.search(r'[;&|`$\n\r<>]', command):
        return False
    if re.fullmatch(r'git\s+(?:diff(?:\s+--check)?|status(?:\s+-sb)?)', command, re.I):
        return True
    prefix=re.fullmatch(r"npm(?:\.cmd)?\s+--prefix\s+([\w./\\-]+|\"[\w ./\\-]+\"|'[\w ./\\-]+')\s+(?:run\s+)?(?:test|typecheck|build)",command,re.I)
    if prefix:
        folder=prefix[1].strip("\"'")
        return not folder.startswith(('/','\\')) and '..' not in re.split(r'[/\\]',folder)
    return bool(re.fullmatch(r"(?:uv\s+run\s+(?:(?:--locked|--no-project)\s+){0,2})?(?:(?:python(?:3)?\s+-m\s+(?:unittest|pytest|compileall)|pytest)\b[\w\s./\\:=,+\-\"']*|npm(?:\.cmd)?\s+(?:run\s+)?(?:test|typecheck|build)(?:\s+--[\w\s./\\:=,+\-\"']*)?)",command,re.I))


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
        if 'recovery_json' not in {row[1] for row in self.db.execute('PRAGMA table_info(task_plan_steps)')}:
            self.db.execute("ALTER TABLE task_plan_steps ADD COLUMN recovery_json TEXT NOT NULL DEFAULT '{}'")
        if 'workflow_json' not in {row[1] for row in self.db.execute('PRAGMA table_info(task_plan_steps)')}:
            self.db.execute("ALTER TABLE task_plan_steps ADD COLUMN workflow_json TEXT NOT NULL DEFAULT '{}'")
        self.db.execute("UPDATE task_plan_executions SET status='interrupted' WHERE status='running'")
        self.db.execute('CREATE TABLE IF NOT EXISTS task_plan_reviews (id INTEGER PRIMARY KEY, plan_id TEXT NOT NULL REFERENCES task_plans(id) ON DELETE CASCADE, step_id TEXT NOT NULL REFERENCES task_plan_steps(id) ON DELETE CASCADE, data_json TEXT NOT NULL)')
        self.db.commit()

    def record_execution(self, plan_id: str, step_id: str, call_id: str, turn_id: str,
                         tool: str, result: dict[str, Any] | None = None, fingerprint: str = "") -> None:
        """Store only execution metadata, never arguments, output, or model reasoning."""
        with self.db:
            data = (result or {}).get("data") or {}
            metadata = {k: data[k] for k in ("process_id", "pid", "shell", "state", "log_path", "metadata_path", "log_truncated", "artifact_id", "path", "width", "height", "dpi", "vision_feedback", "window_id", "window_generation", "sha256", "captured_at", "command_outcome") if k in data}
            if result:
                metadata.update(duration_ms=result.get("duration_ms"), error_code=(result.get("error") or {}).get("code") or data.get("error_code"))
                if not result.get('ok'):
                    from agent.core.execution import failure_diagnosis
                    metadata['diagnosis'] = failure_diagnosis(tool, metadata['error_code'])
                    metadata['error_code'] = metadata['diagnosis']['error_code']
            self.db.execute(
                "INSERT INTO task_plan_executions(call_id,plan_id,step_id,turn_id,tool,status,exit_code,changed_paths,fingerprint,metadata_json) VALUES(?,?,?,?,?,?,?,?,?,?) "
                "ON CONFLICT(call_id) DO UPDATE SET status=excluded.status,exit_code=excluded.exit_code,changed_paths=excluded.changed_paths,metadata_json=excluded.metadata_json",
                (call_id, plan_id, step_id, turn_id, tool,
                 "running" if result is None else "succeeded" if result.get("ok") else "failed",
                 result.get("exit_code") if result else None,
                 json.dumps(list((result or {}).get("changed_paths") or [])[:100]), fingerprint, json.dumps(metadata)),
            )
            if result and result.get('ok'):
                current = self.db.execute('SELECT fingerprint FROM task_plan_executions WHERE call_id=?',(call_id,)).fetchone()
                if current and current[0]:
                    self.db.execute("UPDATE task_plan_executions SET status='reconciled' WHERE plan_id=? AND fingerprint=? AND status='interrupted'",(plan_id,current[0]))

    def executions(self, plan_id):
        return [{"call_id": r["call_id"], "tool": r["tool"], "status": r["status"], "exit_code": r["exit_code"],
                 "metadata": json.loads(r["metadata_json"])} for r in self.db.execute(
                     "SELECT * FROM task_plan_executions WHERE plan_id=? ORDER BY rowid", (plan_id,))]

    def previously_applied(self, plan_id: str, fingerprint: str) -> bool:
        return bool(fingerprint and self.db.execute(
            "SELECT 1 FROM task_plan_executions WHERE plan_id=? AND fingerprint=? AND status='succeeded' AND tool!='start_process' AND tool NOT LIKE 'desktop_%' LIMIT 1",
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
        from agent.core.workflow import normalize_nodes
        graph = normalize_nodes(steps) if any('assigned_role' in s or 'dependencies' in s or 'task_id' in s for s in steps) else None
        plan_id, now = str(uuid.uuid4()), _now()
        with self.db:
            self.db.execute(
                "INSERT INTO task_plans(id,thread_id,goal,created_at,updated_at) VALUES(?,?,?,?,?)",
                (plan_id, thread_id, goal, now, now),
            )
            for i, step in enumerate(steps):
                self.db.execute(
                    "INSERT INTO task_plan_steps(id,plan_id,position,description,verification,workflow_json) VALUES(?,?,?,?,?,?)",
                    (str(uuid.uuid4()), plan_id, i, step["description"], step.get("verification", ""), json.dumps(graph[i] if graph else {})),
                )
        return plan_id

    def append_steps(self, plan_id, steps, *, commit=True):
        """Upgrade complexity without replacing IDs, completed steps or execution evidence."""
        from agent.llm.planning import validate_plan
        validate_plan({'steps':steps})
        plan = self.get(plan_id)
        if len(plan['steps']) + len(steps) > MAX_STEPS:
            raise ValueError('Plan step limit reached')
        graph=any(s['workflow'] for s in plan['steps'])
        new_metadata=None
        if graph:
            from agent.core.workflow import normalize_nodes
            if not all(s['workflow'] for s in plan['steps']):raise ValueError('工作流元数据不完整')
            existing=[{**s['workflow'],'description':s['description'],'verification':s['verification']} for s in plan['steps']]
            referenced={d for s in existing for d in s['dependencies']}
            dependencies=[s['task_id'] for s in existing if s['task_id'] not in referenced]
            expanded=[]
            for source in steps:
                ident=source.get('task_id') or 'append-'+uuid.uuid4().hex[:12]
                expanded.append({**source,'task_id':ident,'assigned_role':source.get('assigned_role','developer'),
                    'dependencies':source.get('dependencies',dependencies)})
                dependencies=[ident]
            if all('assigned_role' not in s for s in steps):
                for role,description in [('reviewer','独立审查追加需求实现，重新读取文件并提交 workflow_review'),('tester','实际运行相关测试，核对 Diff 并交付追加需求')]:
                    ident='append-'+uuid.uuid4().hex[:12]
                    expanded.append({'task_id':ident,'description':description,'assigned_role':role,'dependencies':dependencies})
                    dependencies=[ident]
            normalized=normalize_nodes([*existing,*expanded])
            steps=expanded;new_metadata=normalized[len(existing):]
        elif any('task_id' in s or 'assigned_role' in s or 'dependencies' in s for s in steps):
            raise ValueError('不能隐式改写旧顺序计划的依赖语义')
        with self.db if commit else nullcontext():
            for index, step in enumerate(steps,len(plan['steps'])):
                self.db.execute('INSERT INTO task_plan_steps(id,plan_id,position,description,verification,workflow_json) VALUES(?,?,?,?,?,?)',
                    (str(uuid.uuid4()),plan_id,index,step['description'],step.get('verification',''),json.dumps(new_metadata[index-len(plan['steps'])] if new_metadata else {})))
            self.db.execute('UPDATE task_plans SET updated_at=? WHERE id=?',(_now(),plan_id))
        if commit:self.checkpoint(plan_id,'complexity_upgraded')

    def get(self, plan_id: str) -> dict[str, Any]:
        self.db.row_factory = sqlite3.Row
        plan = self.db.execute("SELECT * FROM task_plans WHERE id=?", (plan_id,)).fetchone()
        if plan is None:
            raise KeyError(plan_id)
        steps = self.db.execute(
            "SELECT * FROM task_plan_steps WHERE plan_id=? ORDER BY position", (plan_id,)
        ).fetchall()
        executions = [{**dict(row), 'metadata':json.loads(row['metadata_json'])} for row in self.db.execute(
            "SELECT call_id,step_id,tool,status,exit_code,metadata_json FROM task_plan_executions WHERE plan_id=? ORDER BY rowid DESC LIMIT 100", (plan_id,))]
        executions.reverse()  # Keep a chronological bounded tail for Task/Plan UI.
        run = self.db.execute('SELECT data_json FROM agent_execution_runs WHERE id=?',(plan_id,)).fetchone() if self.db.execute("SELECT 1 FROM sqlite_master WHERE name='agent_execution_runs'").fetchone() else None
        decoded_steps=[{**dict(s), 'workflow':json.loads(s['workflow_json']), 'recovery':json.loads(s['recovery_json']),
                        'evidence':json.loads(s['evidence_json']),
                        'executions':[item for item in executions if item['step_id']==s['id']]} for s in steps]
        if decoded_steps and all(s['workflow'] for s in decoded_steps):
            from agent.core.workflow import dependency_view
            decoded_steps=dependency_view(decoded_steps)
        return {
            **dict(plan),
            'execution':json.loads(run[0]) if run else None,
            "steps":decoded_steps,
        }

    def set_recovery(self, plan_id, step_id, tool, code):
        from agent.core.execution import failure_diagnosis
        recovery = failure_diagnosis(tool, code)
        with self.db:
            self.db.execute('UPDATE task_plan_steps SET recovery_json=? WHERE plan_id=? AND id=?', (json.dumps(recovery),plan_id,step_id))
        return recovery

    def uncertain_operation(self, plan_id, fingerprint):
        statuses="('interrupted')" if fingerprint=='check' else "('interrupted','reviewed')"
        return bool(fingerprint and self.db.execute(f"SELECT 1 FROM task_plan_executions WHERE plan_id=? AND fingerprint!='' AND status IN {statuses} LIMIT 1",(plan_id,)).fetchone())

    def review_interrupted(self,plan_id,call_id,*,commit=True):
        """显式用户审阅不等于成功；后续修改仍需 fresh approval。"""
        row=self.db.execute("SELECT metadata_json FROM task_plan_executions WHERE plan_id=? AND call_id=? AND status='interrupted'",(plan_id,call_id)).fetchone()
        if not row:raise ValueError('没有待审阅的中断记录')
        metadata={**json.loads(row[0]),'reviewed_at':_now(),'reviewed_by':'explicit_user_approval','result_still_unknown':True}
        with self.db if commit else nullcontext():self.db.execute("UPDATE task_plan_executions SET status='reviewed',metadata_json=? WHERE plan_id=? AND call_id=? AND status='interrupted'",(json.dumps(metadata),plan_id,call_id))

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
        row = self.db.execute('SELECT workflow_json,state FROM task_plan_steps WHERE id=? AND plan_id=?',(step_id,plan_id)).fetchone()
        if row and json.loads(row['workflow_json']) and row['state']=='completed':
            return
        if row and json.loads(row['workflow_json']) and state in {'completed','in_progress'} and row['state']!='completed':
            all_steps=self.get(plan_id)['steps']
            completed={s['workflow']['task_id'] for s in all_steps if s['state']=='completed'}
            if not set(json.loads(row['workflow_json'])['dependencies'])<=completed:
                raise ValueError('子任务依赖尚未完成')
            if state=='completed':
                actual=self.execution_evidence(plan_id,step_id,[e.get('tool_call_id') for e in evidence])
                role=json.loads(row['workflow_json'])['assigned_role']
                if role=='reviewer':
                    verdict=self.db.execute('SELECT data_json FROM task_plan_reviews WHERE plan_id=? AND step_id=? ORDER BY id DESC LIMIT 1',(plan_id,step_id)).fetchone()
                    if not verdict or json.loads(verdict[0])['decision']!='approved':
                        raise ValueError('Reviewer 必须提交基于真实读取证据的独立审查结论')
                if role=='tester' and not any(e['tool']=='run_command' and e['exit_code']==0 for e in actual):
                    raise ValueError('Tester 完成必须有真实命令的成功退出码')
        with self.db:
            previous = self.db.execute(
                "SELECT state FROM task_plan_steps WHERE id=? AND plan_id=?",
                (step_id, plan_id),
            ).fetchone()
            if previous is None:
                raise KeyError(step_id)
            # Completed work has persisted tool evidence. A stale executor or
            # replayed tool call must never turn it back into in_progress/blocked.
            if previous["state"] == "completed" and state != "completed":
                return
            result = self.db.execute(
                "UPDATE task_plan_steps SET state=?,evidence_json=? WHERE id=? AND plan_id=?",
                (state, json.dumps(evidence) if evidence is not None else
                 (self.db.execute("SELECT evidence_json FROM task_plan_steps WHERE id=? AND plan_id=?",
                                  (step_id, plan_id)).fetchone()[0]), step_id, plan_id),
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
            'execution':plan.get('execution'),
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
        """Legacy plans remain sequential; DAG plans choose dependency-ready work."""
        steps = self.get(plan_id)['steps']
        if steps and all(s['workflow'] for s in steps):
            from agent.core.workflow import ready_steps
            ready = ready_steps(steps)
            if ready:
                return ready[0]
            # A blocked/skipped dependency is not a completed workflow.
            return (next((s for s in steps if s['state']=='blocked' and not s.get('dependency_blocked')),None)
                    or next((s for s in steps if s['state']=='blocked'),None)
                    or next((s for s in steps if s['state']!='completed'),None))
        return next((step for step in steps
                     if step["state"] not in ("completed", "skipped")), None)

    def revise_workflow(self, plan_id: str, changes: dict[str, dict], reason: str) -> None:
        """Atomically revise pending nodes only; preserve IDs and actual evidence."""
        from agent.core.workflow import normalize_nodes
        plan = self.get(plan_id)
        if not isinstance(reason, str) or not reason.strip() or len(reason)>2000:
            raise ValueError('调整计划必须提供有界原因')
        if not all(s['workflow'] for s in plan['steps']):
            raise ValueError('旧顺序计划不能隐式转换依赖图')
        known = {s['workflow']['task_id']:s for s in plan['steps']}
        if not changes or set(changes)-known.keys():
            raise ValueError('调整引用不存在的子任务')
        for ident, delta in changes.items():
            if (known[ident]['state']!='pending' and not known[ident].get('dependency_blocked')) or not isinstance(delta,dict) or set(delta)-{'description','verification','dependencies','acceptance_criteria','required_capabilities','title'}:
                raise ValueError('只能调整尚未执行步骤的允许字段')
            for field,maximum in [('description',4000),('verification',2000)]:
                if field in delta and (not isinstance(delta[field],str) or len(delta[field])>maximum or field=='description' and not delta[field].strip()):raise ValueError('步骤描述或验证命令无效')
        nodes = [{**s['workflow'], 'description':s['description'], **changes.get(s['workflow']['task_id'],{})} for s in plan['steps']]
        validated = normalize_nodes(nodes)
        with self.db:
            for step, node in zip(plan['steps'],validated):
                if step['workflow']['task_id'] not in changes:continue
                node['retry_count']=step['workflow'].get('retry_count',0)
                node['adjustment_reason']=reason
                delta=changes[step['workflow']['task_id']]
                self.db.execute('UPDATE task_plan_steps SET workflow_json=?,description=?,verification=? WHERE id=? AND plan_id=?',
                    (json.dumps(node),delta.get('description',step['description']),delta.get('verification',step['verification']),step['id'],plan_id))
            self.checkpoint(plan_id,'workflow_adjusted')

    def review_workflow(self, plan_id, step_id, decision, summary, *, max_repairs=3, allow_repair=True):
        """Independent review may insert repairs, never undo completed nodes."""
        if decision not in {'approved','request_changes'} or not isinstance(summary,str) or not 1<=len(summary.strip())<=2000:
            raise ValueError('审查结论无效')
        plan=self.get(plan_id)
        step=self.active_step(plan_id)
        if not step or step['id']!=step_id or step.get('workflow',{}).get('assigned_role')!='reviewer':
            raise ValueError('只有当前 Reviewer 可以提交审查')
        meta=step['workflow']
        prior=self.db.execute('SELECT data_json FROM task_plan_reviews WHERE plan_id=? AND step_id=? ORDER BY id DESC LIMIT 1',(plan_id,step_id)).fetchone()
        used=set(json.loads(prior[0]).get('evidence_ids',[])) if prior else set()
        actual=[dict(r) for r in self.db.execute("SELECT * FROM task_plan_executions WHERE plan_id=? AND step_id=? AND status='succeeded' AND (exit_code IS NULL OR exit_code=0)",(plan_id,step_id)) if r['call_id'] not in used and r['tool'] in {'read_file','git_diff','knowledge_search','search_files'}]
        if not actual:
            raise ValueError('必须重新执行独立读取或 Diff 检查，不能仅引用先前文字')
        verdict={'decision':decision,'summary':summary,'evidence_ids':sorted(used|{r['call_id'] for r in actual})}
        with self.db:
            if decision=='request_changes':
                retries=meta.get('retry_count',0)
                if not allow_repair or retries>=max_repairs or len(plan['steps'])>=30:
                    self.update_step(plan_id,step_id,'blocked')
                    self.checkpoint(plan_id,'review_repair_limit')
                    return {'decision':'blocked','reason':'独立审查修复达到上限，原证据保留'}
                repair_id=str(uuid.uuid4())
                local_id='repair-'+repair_id[:12]
                repair={'task_id':local_id,'title':'修复独立审查问题','dependencies':meta['dependencies'],
                    'assigned_role':'developer','required_capabilities':['tool_calling'],
                    'acceptance_criteria':[summary],'retry_count':retries+1}
                self.db.execute('INSERT INTO task_plan_steps(id,plan_id,position,description,verification,workflow_json) VALUES(?,?,?,?,?,?)',
                    (repair_id,plan_id,len(plan['steps']),'修复审查指出的问题：'+summary,'',json.dumps(repair)))
                meta={**meta,'dependencies':[local_id],'retry_count':retries+1}
                self.db.execute("UPDATE task_plan_steps SET state='pending',workflow_json=? WHERE id=? AND plan_id=?",(json.dumps(meta),step_id,plan_id))
            self.db.execute('INSERT INTO task_plan_reviews(plan_id,step_id,data_json) VALUES(?,?,?)',(plan_id,step_id,json.dumps(verdict)))
            self.checkpoint(plan_id,'independent_review')
        return verdict

    def prepare_missing_test_handoff(self, plan_id, step_id):
        """One bounded Developer handoff, without inventing a test failure."""
        step = self.active_step(plan_id)
        if not step or step['id'] != step_id or step['workflow'].get('assigned_role') != 'tester':
            raise ValueError('只能退回当前 Tester 步骤')
        meta = step['workflow']
        steps = self.get(plan_id)['steps']
        with self.db:
            if meta.get('handoff_requested') or len(steps) >= 30:
                self.update_step(plan_id,step_id,'blocked')
                self.checkpoint(plan_id,'missing_test_handoff_blocked')
                return False
            ident = str(uuid.uuid4())
            local = 'tests-' + ident[:12]
            title = '为已实现的交付创建一个隔离验证脚本并提交 workflow_test_handoff'
            node = {'task_id':local,'title':title,'dependencies':meta['dependencies'],
                    'assigned_role':'developer','acceptance_criteria':[title],
                    'required_capabilities':['tool_calling'],'retry_count':0,'handoff_for':step_id}
            self.db.execute(
                'INSERT INTO task_plan_steps(id,plan_id,position,description,verification,workflow_json) VALUES(?,?,?,?,?,?)',
                (ident,plan_id,len(steps),title,'',json.dumps(node)))
            self.db.execute("UPDATE task_plan_steps SET state='pending',workflow_json=? WHERE id=? AND plan_id=?",
                (json.dumps({**meta,'dependencies':[local],'handoff_requested':True}),step_id,plan_id))
            self.checkpoint(plan_id,'tester_missing_test_returned_to_developer')
        return True

    def repair_test_failure(self, plan_id, step_id, summary, *, max_repairs=3):
        """Route real failing tests back through Developer and a fresh Reviewer."""
        step=self.active_step(plan_id)
        if not step or step['id']!=step_id or step.get('workflow',{}).get('assigned_role')!='tester':
            raise ValueError('只有当前 Tester 可以退回测试失败')
        failed=self.db.execute("SELECT 1 FROM task_plan_executions WHERE plan_id=? AND step_id=? AND tool='run_command' AND status='failed' LIMIT 1",(plan_id,step_id)).fetchone()
        if not failed:raise ValueError('没有真实测试命令失败证据')
        meta=step['workflow'];plan=self.get(plan_id)
        with self.db:
            if meta.get('retry_count',0)>=max_repairs or len(plan['steps'])+2>30:
                self.update_step(plan_id,step_id,'blocked')
                self.checkpoint(plan_id,'test_repair_limit')
                return False
            repair_id,review_id=str(uuid.uuid4()),str(uuid.uuid4())
            repair_local,review_local='repair-'+repair_id[:12],'review-'+review_id[:12]
            for i,(ident,local,role,deps,text) in enumerate([
                (repair_id,repair_local,'developer',meta['dependencies'],'修复真实测试失败：'+summary[:2000]),
                (review_id,review_local,'reviewer',[repair_local],'独立检查测试失败的修复，重新读取文件并提交 workflow_review')]):
                node={'task_id':local,'title':text[:200],'dependencies':deps,'assigned_role':role,
                      'acceptance_criteria':[summary[:2000] if role=='developer' else '独立审查通过'],
                      'required_capabilities':['tool_calling'],'retry_count':0}
                self.db.execute('INSERT INTO task_plan_steps(id,plan_id,position,description,verification,workflow_json) VALUES(?,?,?,?,?,?)',
                    (ident,plan_id,len(plan['steps'])+i,text,'',json.dumps(node)))
            meta={**meta,'dependencies':[review_local],'retry_count':meta.get('retry_count',0)+1}
            self.db.execute("UPDATE task_plan_steps SET state='pending',workflow_json=? WHERE id=? AND plan_id=?",(json.dumps(meta),step_id,plan_id))
            self.checkpoint(plan_id,'test_returned_to_developer')
        return True

    def advance_verified(self, plan_id: str, step_id: str,
                         evidence: list[dict[str, Any]],
                         verification_passed: bool) -> bool:
        """Only complete the first unfinished, unblocked step with tool evidence."""
        current = self.active_step(plan_id)
        if not current or current["id"] != step_id or current["state"] == "blocked":
            return False
        if current.get('workflow'):
            from agent.core.workflow import ready_steps
            if step_id not in {s['id'] for s in ready_steps(self.get(plan_id)['steps'])}:
                return False
        if not verification_passed or not evidence:
            return False
        if not all(item.get("ok") is True for item in evidence):
            return False
        if current.get('workflow'):
            # Expected nonzero probes remain in the execution journal. Do not
            # let them invalidate independent zero-exit step evidence.
            accepted = []
            for item in evidence:
                if item.get("exit_code") in (None, 0):
                    accepted.append(item)
                    continue
                row = self.db.execute(
                    "SELECT exit_code, status, metadata_json FROM task_plan_executions "
                    "WHERE plan_id=? AND step_id=? AND call_id=? AND tool='run_command'",
                    (plan_id, step_id, item.get("tool_call_id")),
                ).fetchone()
                if (not row or row["status"] != "succeeded" or row["exit_code"] != item["exit_code"]
                        or json.loads(row["metadata_json"]).get("command_outcome", {}).get("status") != "expected_exit"):
                    return False
            evidence = accepted
            from agent.plan_verification import verification_passed as step_verified
            if not step_verified(step_id, current["verification"], evidence, loop_complete=True):
                return False
        try:
            self.update_step(plan_id, step_id, "completed", evidence)
        except ValueError:
            return False
        return True

    def prepare_resume(self, plan_id: str) -> dict[str, Any]:
        """Explicit, non-executing resume: identify the first unfinished step.

        Completed and skipped steps are never reset or replayed. A previously
        in-progress step is left intact until the user verifies the workspace.
        """
        plan = self.get(plan_id)
        checkpoint = self.latest_checkpoint(plan_id)
        next_step = self.active_step(plan_id)
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
