"""Local-first orchestration around the v0.3 Agent Loop and Task Plans."""
from __future__ import annotations

import asyncio
from contextlib import suppress
from dataclasses import asdict, replace
import json
import hashlib
from pathlib import Path
import re
import time

from agent.core.budget import BudgetExceeded, BudgetGuard, validate_limits
from agent.core.diagnostics import redact_text
from agent.core.settings import RuntimeSettings
from agent.core.model_catalog import ModelCatalog, validate_catalog, KEY as CATALOG_KEY
from agent.llm.ollama import OllamaProvider
from agent.llm.openai_compatible import OpenAICompatibleProvider
from agent.core.verification import VerificationEngine, discover_commands, failure_fingerprint
from agent.llm.base import ProviderError, ToolCall
from agent.llm.router import ModelRouter, json_object, validate_config, apply_config_overrides
from agent.llm.planning import PLAN_PROMPT, PLAN_SCHEMA
from agent.server.protocol import envelope, new_id
from agent.tools.registry import ToolRegistry
from agent.tools.workspace import Workspace


def autonomous_git_block(name: str, arguments: dict) -> str:
    if name in {"write_file", "apply_patch"} and ".git" in re.split(r"[/\\]+", str(arguments.get("path", "")).lower()):
        return "Task Git metadata is protected; use the explicit Git workflow."
    if name in {"git_commit", "git_worktree_remove", "git_worktree_create"}:
        return "Autonomous execution stops at Git review; use the explicit Git workflow after reviewing tests and Diff."
    command = str(arguments.get("command", "")) if name == "run_command" else ""
    if re.search(r"\bgit\b[^\r\n;&|]*\b(?:commit|push|merge|rebase|reset|clean|checkout|switch|worktree)\b", command, re.I):
        return "Git history, publishing and workspace switching require the explicit Git workflow."
    return ""


class LoopRelay:
    """Forward original tool/stream events; independent validation owns final completion."""
    def __init__(self, ws, turn_id):
        self.ws, self.outcome, self.turn_id = ws, None, turn_id

    async def send_json(self, event):
        if event["type"] in {"turn.completed", "turn.failed", "turn.cancelled"}:
            self.outcome = event
        elif event["type"] != "plan.completed":
            await self.ws.send_json({**event, "turn_id": self.turn_id})


class TaskService:
    def __init__(self, server):
        self.server, self.runtime = server, server.store.task_runtime
        self.runtime.recover()
        self.running: dict[str, str] = {}
        self.stop_reasons: dict[str, str] = {}
        self.provider_factory_override = None  # Dependency injection for deterministic tests.
        self.credentials = {}  # Memory only; Electron safeStorage owns persistence.

    def catalog(self):
        return ModelCatalog(self.server.store, self.server.settings)

    def settings(self) -> dict:
        self.catalog().load()  # Idempotent migration before reading role defaults.
        raw = self.server.store.get_setting("orchestration.config")
        return validate_config(json.loads(raw) if raw else None)

    def public(self, task: dict) -> dict:
        return {**task, "usage": self.runtime.usage(task["id"]),
                "calls": self.runtime.calls(task["id"]), "plan": self.runtime.plans.get(task["id"]),
                "checkpoint": self.runtime.plans.latest_checkpoint(task["id"])}

    async def handle(self, ws, data: dict, owned_turns: set):
        kind, payload = data["type"], data.get("payload", {})
        request_id = data.get("request_id")
        thread_id = str(data.get("thread_id") or payload.get("thread_id") or "")
        project = self.server.projects.active
        try:
            if kind == "task.credentials.update":
                values = payload.get("credentials")
                if not isinstance(values, dict) or any(not isinstance(k, str) or not k.startswith("connection-") or not isinstance(v, str) or len(v) > 16000 for k, v in values.items()):
                    raise ValueError("Invalid provider credentials")
                if self.server.active_turns:
                    raise ValueError("Pause active execution before changing credentials")
                self.credentials = dict(values)
                result = {"configured": list(values)}
            elif kind == "task.catalog.get":
                result = {"catalog": self.catalog().load(), "config": self.settings(), "global_usage":self.runtime.usage()}
            elif kind == "task.catalog.update":
                catalog = validate_catalog(payload.get("catalog"))
                config = validate_config(payload.get("config") or self.settings())
                self.catalog().resolve(config, catalog)  # Reject dangling/disabled role bindings.
                with self.server.store.connection:
                    for key, value in ((CATALOG_KEY, catalog), ("orchestration.config", config)):
                        self.server.store.connection.execute("INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, json.dumps(value)))
                result = {"catalog": catalog, "config": config}
            elif kind == "task.settings.get":
                result = {"config": self.settings(), "global_usage": self.runtime.usage()}
            elif kind == "task.settings.update":
                if self.server.active_turns:
                    raise ValueError("Pause active execution before changing task settings")
                config = validate_config(payload.get("config"))
                self.catalog().resolve(config)
                self.server.store.set_setting("orchestration.config", json.dumps(config))
                result = {"config": config, "global_usage": self.runtime.usage()}
            elif kind == "task.connection.test":
                cid = payload.get("connection_id")
                if cid:
                    connection = next((c for c in self.catalog().load()["connections"] if c["connection_id"] == cid), None)
                    if not connection or not connection["enabled"]:
                        raise ValueError("Provider connection missing or disabled")
                    route = "local" if connection["provider_type"] == "ollama" else "api"
                    provider = self.make_provider({}, route, {"_connection": connection})
                else:
                    route = payload.get("route")
                    if route not in {"local", "api"}:
                        raise ValueError("Connection route must be local or api")
                    provider = self.make_provider(asdict(self.server.settings), route, {})
                result = await provider.get_status()
                if hasattr(provider, "capabilities") and provider.preferred_model:
                    result["capabilities"] = await provider.capabilities(provider.preferred_model)
                result["generates_tokens"] = False
                if isinstance(result.get("error"), dict):
                    result["error"]["message"] = redact_text(str(result["error"].get("message", "")), exact_secrets=self.server._exact_secrets(), max_chars=2000)
            else:
                if not project or not project.state.get_thread(thread_id):
                    raise ValueError("Open a valid project and thread")
                if kind == "task.list":
                    result = {"tasks": [self.public(t) for t in self.runtime.list(thread_id)]}
                elif kind == "task.start":
                    if any(not t.done() for t in self.server.active_turns.values()):
                        raise ValueError("Pause or stop the active task first")
                    goal = str(payload.get("goal") or "").strip()
                    if not 1 <= len(goal) <= 16000:
                        raise ValueError("Task goal must contain 1..16000 characters")
                    saved = self.settings()
                    if "config" in payload and "config_overrides" in payload:
                        raise ValueError("Specify configuration or overrides, not both")
                    if "config_overrides" in payload:
                        config = apply_config_overrides(saved, payload["config_overrides"])
                        config_source = "saved-settings-with-overrides" if payload["config_overrides"] else "saved-settings"
                    else:
                        config = validate_config(payload["config"] if "config" in payload else saved)
                        config_source = "explicit-config" if "config" in payload else "saved-settings"
                    resolved = self.catalog().resolve(config)
                    if any(p for p in self.runtime.plans.list_for_thread(thread_id)
                           if self.runtime.plans.active_step(p["id"]) and not self.runtime.db.execute(
                               "SELECT 1 FROM autonomous_tasks WHERE plan_id=?", (p["id"],)).fetchone()):
                        raise ValueError("Finish or use a new thread for the existing manual plan")
                    task = self.runtime.create(thread_id, goal, config, str(project.workspace.root))
                    task["provider_settings"] = asdict(self.server.settings)  # No keys in settings.
                    task["resolved_roles"] = resolved["roles"]
                    task["global_budget"] = saved["budget"]
                    task["config_source"] = config_source
                    task["config_snapshot_at"] = time.time()
                    self.runtime.save(task)
                    result = {"task": self.public(task), "defaults":saved, "catalog":self.catalog().load(), "global_usage":self.runtime.usage()}
                    await ws.send_json(envelope("task.loaded", result, request_id=request_id, thread_id=thread_id))
                    self.launch(ws, task, project, owned_turns)
                    return
                else:
                    task = self.runtime.get(str(payload.get("task_id") or ""))
                    if task["thread_id"] != thread_id:
                        raise ValueError("Task belongs to another thread")
                    plan_id = task["id"]
                    if kind in {"task.pause", "task.cancel"}:
                        turn_id = self.running.get(plan_id)
                        running = self.server.active_turns.get(turn_id)
                        if running and not running.done():
                            self.stop_reasons[plan_id] = "paused" if kind == "task.pause" else "cancelled"
                            self.server.approvals.cancel_turn(turn_id)
                            running.cancel()
                            await asyncio.gather(running, return_exceptions=True)
                            target = "paused" if kind == "task.pause" else "cancelled"
                            if self.runtime.get(plan_id)["status"] != target:
                                self.runtime.transition(plan_id, target, "User requested")
                            self.stop_reasons.pop(plan_id, None)
                            self.running.pop(plan_id, None)
                        else:
                            task["last_error"] = {"code":"TASK_PAUSED" if kind == "task.pause" else "TASK_CANCELLED"}
                            self.runtime.save(task)
                            self.runtime.transition(plan_id, "paused" if kind == "task.pause" else "cancelled", "User requested")
                    elif kind == "task.resume":
                        if any(not t.done() for t in self.server.active_turns.values()):
                            raise ValueError("Stop the active task first")
                        if payload.get("confirm_workspace") is not True:
                            raise ValueError("Review workspace and checkpoint, then explicitly confirm recovery")
                        if task["status"] not in {"paused", "failed", "cancelled", "completed", "awaiting_approval"}:
                            raise ValueError("Task cannot be resumed in its current state")
                        if task["status"] != "paused":
                            self.runtime.transition(plan_id, "paused", "User reopened task")
                        task = self.runtime.get(plan_id)
                        if payload.get("local_only") is True:
                            task["config"]["strategy"] = "local-only"
                            self.runtime.save(task)
                        self.launch(ws, task, project, owned_turns)
                    elif kind == "task.budget.add":
                        if task["status"] != "paused":
                            raise ValueError("Pause task before explicitly changing its budget")
                        budget = validate_limits({**task["config"]["budget"], **payload.get("budget", {})})
                        task["config"]["budget"] = budget
                        task["config_source"] = "paused-task-budget-update"
                        task["config_snapshot_at"] = time.time()
                        if any(k.startswith("global_") for k in payload.get("budget", {})):
                            task["global_budget"] = {**task.get("global_budget", budget),
                                **{k: budget[k] for k in payload["budget"] if k.startswith("global_")}}
                        self.runtime.save(task)
                    elif kind == "task.diagnostics":
                        result = self.diagnostics(plan_id)
                        await ws.send_json(envelope("task.loaded", result, request_id=request_id, thread_id=thread_id))
                        return
                    elif kind == "task.configure":
                        if task["status"] != "paused":
                            raise ValueError("Pause task before explicitly changing its configuration")
                        task["config"] = validate_config(payload.get("config"))
                        task["resolved_roles"] = self.catalog().resolve(task["config"])["roles"]
                        task["global_budget"] = self.settings()["budget"]
                        task["provider_settings"] = asdict(self.server.settings)
                        task["config_source"] = "paused-task-configuration"
                        task["config_snapshot_at"] = time.time()
                        task.pop("resolved_verification_commands", None)
                        self.runtime.save(task)
                    elif kind == "task.approve":
                        if task["status"] != "awaiting_approval":
                            raise ValueError("Only independently verified tasks can be accepted")
                        # Revalidation after manual editing is required, never accept a stale Diff.
                        view = self.task_project(task, project)
                        current = await view.tools.execute("git_diff", {})
                        if current.to_dict().get("stdout", "") != task["report"].get("diff", "") or await self.workspace_fingerprint(view) != task["report"].get("workspace_fingerprint"):
                            raise ValueError("Diff changed since verification. Reopen and verify again.")
                        self.runtime.transition(plan_id, "completed", "User accepted verified report. No automatic Git commit/push/merge.")
                    else:
                        raise ValueError("Unsupported task operation")
                    result = {"task": self.public(self.runtime.get(plan_id))}
            await ws.send_json(envelope("task.loaded", result, request_id=request_id, thread_id=thread_id or None))
        except (ValueError, TypeError, KeyError, OSError, ProviderError) as exc:
            await self.server.send_error(ws, "TASK_INVALID", redact_text(str(exc), exact_secrets=self.server._exact_secrets()), request_id=request_id, thread_id=thread_id or None)

    def make_provider(self, snapshot, route, profile):
        if self.provider_factory_override:
            return self.provider_factory_override(route, profile)
        connection = profile.get("_connection")
        if connection:
            kwargs = {"base_url": connection["base_url"], "preferred_model": profile.get("model", ""),
                      "context_window": profile.get("context_window") or 32768,
                      "temperature": profile.get("temperature") if profile.get("temperature") is not None else 0.2}
            if connection["provider_type"] == "ollama":
                return OllamaProvider(**kwargs)
            ref = connection["credential_reference"]
            key = self.server.openai_api_key if ref == "legacy-openai" else self.credentials.get(ref, "")
            return OpenAICompatibleProvider(**kwargs, api_key=key or "")
        settings = RuntimeSettings.validate({**snapshot, "provider": "ollama" if route == "local" else "openai_compatible"})
        return settings.create_provider(openai_api_key=self.server.openai_api_key)

    def task_project(self, task, source):
        root = Path(task["workspace"])
        # Only persisted managed worktrees belonging to this source are eligible.
        if not root.is_dir() or root.resolve() == Path(task["source"]).resolve():
            raise ValueError("Task worktree missing or points to source workspace")
        workspace = Workspace(str(root))
        return replace(source, workspace=workspace, tools=ToolRegistry(workspace), repository_map=None)

    def launch(self, ws, task, project, owned_turns):
        turn_id = new_id("turn")
        self.running[task["id"]] = turn_id
        owned_turns.add(turn_id)
        running = asyncio.create_task(self.run(ws, task["id"], project, turn_id), name=turn_id)
        self.server.active_turns[turn_id] = running
        running.add_done_callback(lambda _: self.server.active_turns.pop(turn_id, None))

    async def workspace_fingerprint(self, project):
        # Track all nonignored files, including untracked files missing from Git diff.
        from agent.tools.git import _git
        code, names, _ = await _git(project.workspace, "ls-files", "-co", "--exclude-standard", "-z")
        if code:
            raise ValueError("Cannot snapshot task worktree for review")
        digest, total = hashlib.sha256(), 0
        paths = sorted(set(filter(None, names.split("\0"))))
        if len(paths) > 10000:
            raise ValueError("Review snapshot exceeds 10000 files; configure Git ignore and retry")
        for name in paths:
            path = project.workspace.resolve(name)
            digest.update(name.encode("utf-8"))
            if not path.exists():
                digest.update(b"deleted")
                continue
            if not path.is_file():
                raise ValueError("Unsupported nested repository in review snapshot")
            total += path.stat().st_size
            if total > 100 * 1024 * 1024:
                raise ValueError("Review snapshot exceeds 100 MiB; configure Git ignore and retry")
            with path.open("rb") as handle:
                while chunk := handle.read(65536):
                    digest.update(chunk)
        return digest.hexdigest()

    async def run(self, ws, plan_id, source, turn_id):
        task = self.runtime.get(plan_id)
        task.pop("last_error", None)
        self.runtime.save(task)
        thread_id, goal = task["thread_id"], task["goal"]
        async def emit(kind, payload):
            await ws.send_json(envelope(kind, payload, thread_id=thread_id, turn_id=turn_id))
        async def update(status, reason="", **values):
            self.runtime.transition(plan_id, status, reason, **values)
            await emit("task.updated", {"task": self.public(self.runtime.get(plan_id))})
        try:
            await emit("turn.started", {"prompt": goal, "model": "Task router", "provider": "local-first", "project_id": source.id})
            remaining = task["config"]["budget"]["task_seconds"] - task["elapsed_seconds"]
            if remaining <= 0:
                raise BudgetExceeded("Task execution time exhausted; explicitly add time before recovery")
            async with asyncio.timeout(remaining):
                await update("planning" if not task["planned"] else "executing", "Inspect workspace before resuming; completed mutations are not replayed", report={})
                budget = BudgetGuard(self.runtime, plan_id, task["global_budget"] if "global_budget" in task else self.settings()["budget"])
                router = ModelRouter(task["config"], lambda route, profile: self.make_provider(task["provider_settings"], route, profile), budget, emit, task.get("resolved_roles"))
                # Validate the task's frozen routes before worktree approval or HTTP.
                for role in ("planner", "executor", "reviewer"):
                    router.resolve(role)
                if not task["workspace"]:
                    # Existing worktree policy still requires explicit intent and Approval.
                    result = await self.server._authorize_tool(ws, project=source,
                        call=ToolCall("git_worktree_create", {"task_name": "task-" + plan_id[:12], "branch": "lca/task-" + plan_id[:12]}),
                        call_id=turn_id + ":isolate", thread_id=thread_id, turn_id=turn_id,
                        user_prompt="Create an isolated task worktree for this autonomous task. " + goal)
                    if not result.get("ok"):
                        await update("paused", "Isolated worktree unavailable or approval denied; source files were not modified")
                        return
                    task = self.runtime.get(plan_id)
                    task.update(workspace=result["data"]["path"], branch=result["data"]["branch"])
                    self.runtime.save(task)
                view = self.task_project(task, source)
                # Verify persisted path against git's own managed-worktree records on recovery.
                records = await source.tools.execute("git_worktree_list", {})
                if not any(Path(r["path"]).resolve() == view.workspace.root.resolve() and r.get("managed") for r in records.data.get("worktrees", [])):
                    raise ValueError("Persisted task path is not a managed worktree of the source repository")
                view.workspace.set_full_access(self.server.permissions.mode.value == "full_access")
                self.server.mcp_runtime.apply_to_project(view)
                task = self.runtime.get(plan_id)
                if "resolved_verification_commands" not in task:
                    # Model edits must never weaken the verification command contract.
                    task["resolved_verification_commands"] = discover_commands(view.workspace.root, task["config"]["verification_commands"])
                    self.runtime.save(task)
                commands = task["resolved_verification_commands"]
                async def execute(name, arguments, on_raw_output=None, environment=None):
                    return await self.server._authorize_tool(ws, project=view, call=ToolCall(name, arguments),
                        call_id=new_id("verification"), thread_id=thread_id, turn_id=turn_id,
                        user_prompt=goal, autonomous=True, on_raw_output=on_raw_output, environment=environment)
                verifier = VerificationEngine(self.server.store.data_dir / "verification" / plan_id, execute, task["config"]["budget"]["verification_seconds"])
                advice = ""
                # A fixed safety bound supplements configurable time and API limits.
                for _ in range(200):
                    task = self.runtime.get(plan_id)
                    if not task["planned"]:
                        limit = task["config"]["budget"].get("planning_attempts", 4)
                        if task.get("planning_attempts", 0) >= limit:
                            raise ProviderError("PLAN_RETRY_LIMIT", "Planning attempt limit reached; inspect Task diagnostics before changing the paused task configuration")
                        task["planning_attempts"] = task.get("planning_attempts", 0) + 1
                        self.runtime.save(task)
                        try:
                            steps = await router.plan([{"role":"system", "content":PLAN_PROMPT},
                                {"role":"user", "content":goal + ("\nPrevious plan error / diagnostic advice: " + advice if advice else "")}])
                            self.runtime.replace_unstarted_steps(plan_id, steps)
                            task = self.runtime.get(plan_id)
                            task["planned"] = True
                            self.runtime.save(task)
                        except ProviderError as exc:
                            if exc.code not in {"MODEL_INVALID_RESULT", "PLAN_JSON_INVALID", "PLAN_SCHEMA_INVALID", "PLAN_EMPTY", "PLAN_TRUNCATED", "PLAN_UNEXPECTED_TOOL"}:
                                raise
                            task = self.runtime.get(plan_id)
                            calls = self.runtime.calls(plan_id)
                            last = next((c["usage"] for c in reversed(calls) if c["id"] == getattr(router, "last_plan_call_id", None)), {})
                            previous = task.get("planning_failures", [])
                            current = {"code":exc.code, "fingerprint":last.get("response_fingerprint"), "call_id":getattr(router, "last_plan_call_id", None)}
                            task["planning_failures"] = [*previous, current][-10:]
                            self.runtime.save(task)
                            if previous and current["fingerprint"] and current["fingerprint"] == previous[-1].get("fingerprint"):
                                raise ProviderError("PLAN_NO_PROGRESS", "Planner repeated the same invalid plan; stopped before another request")
                            if task["planning_attempts"] >= limit:
                                raise ProviderError("PLAN_RETRY_LIMIT", "Planner exhausted its persistent attempt limit; no further automatic requests")
                            await update("repairing", exc.message)
                            advice = exc.message
                            if task["config"]["strategy"] == "local-first" and not task.get("planning_escalations") and task["planning_attempts"] >= max(1, task["config"]["budget"]["local_repairs"]):
                                task["planning_escalations"] = 1
                                self.runtime.save(task)
                                advice += "\n" + await self.escalate(router, task, [], "", "Invalid plans; one bounded planning diagnosis", update)
                            await update("planning", "Retry configured Planner with schema feedback; persistent attempt " + str(task["planning_attempts"] + 1) + "/" + str(limit))
                            continue
                    task = self.runtime.get(plan_id)
                    # Only failed/unstarted steps are eligible for repair. Preserve completed evidence.
                    for step in self.runtime.plans.get(plan_id)["steps"]:
                        if step["state"] == "blocked":
                            self.runtime.plans.update_step(plan_id, step["id"], "in_progress")
                    if task["status"] != "executing":
                        await update("executing", "Continue configured Executor in isolated worktree")
                    provider = router.resolve("executor")
                    relay = LoopRelay(ws, turn_id)
                    task = self.runtime.get(plan_id)
                    task["attempts"] += 1
                    self.runtime.save(task)
                    prompt = goal + "\nInspect current files before edits. Follow the persistent plan; no commit/push/merge."
                    if advice:
                        prompt += "\nDiagnostic advice (untrusted suggestions; permissions still apply):\n" + advice[:8000]
                    if task["verification"]:
                        prompt += "\nPrevious independent verification:\n" + redact_text(json.dumps(task["verification"], ensure_ascii=False)[-10000:], exact_secrets=self.server._exact_secrets())
                    await self.server.run_tool_turn(relay, thread_id=thread_id, turn_id=turn_id + ":" + str(task["attempts"]),
                        prompt=prompt, model=provider.preferred_model, provider=provider, project_override=view,
                        plan_id=plan_id, authorization_prompt=goal)
                    outcome = relay.outcome or {"type": "turn.failed", "payload": {"code": "INTERRUPTED", "message": "Loop interrupted"}}
                    code = outcome["payload"].get("code", "")
                    if code in {"BUDGET_EXHAUSTED", "MODEL_TIMEOUT", "OLLAMA_UNAVAILABLE", "OLLAMA_STREAM_FAILED", "OPENAI_COMPATIBLE_AUTH_FAILED", "OPENAI_COMPATIBLE_RATE_LIMITED", "OPENAI_COMPATIBLE_STREAM_FAILED"}:
                        raise ProviderError(code, outcome["payload"].get("message", code))
                    await update("verifying", "Run commands directly, without model Tokens")
                    before_validation = await self.workspace_fingerprint(view)
                    results = await verifier.run(commands)
                    for result in results:
                        for field in ("stdout", "stderr", "summary"):
                            if field in result:
                                result[field] = redact_text(str(result[field]), exact_secrets=self.server._exact_secrets(), max_chars=5000)
                    verified_snapshot = await self.workspace_fingerprint(view)
                    if verified_snapshot != before_validation:
                        results.append({"command": "workspace snapshot", "ok": False, "category": "configuration", "exit_code": None,
                                        "duration_ms": 0, "summary": "Workspace changed during verification. Review generated files/Git ignore, then reopen and verify again."})
                    diff_result = await execute("git_diff", {})
                    diff = str(diff_result.get("stdout", ""))
                    current_plan = self.runtime.plans.get(plan_id)
                    plan_complete = all(s["state"] == "completed" for s in current_plan["steps"])
                    passed = bool(results) and all(r["ok"] for r in results) and diff_result.get("ok") and plan_complete and outcome["type"] == "turn.completed"
                    fingerprint = failure_fingerprint(results, diff)
                    task = self.runtime.get(plan_id)
                    history = [*task["attempt_history"], {"fingerprint": fingerprint, "reason": code or "verification", "attempt": task["attempts"]}][-30:]
                    task.update(verification=results, attempt_history=history)
                    self.runtime.save(task)
                    await emit("verification.completed", {"results": results, "passed": bool(passed)})
                    if passed:
                        review = await router.text("reviewer", [{"role": "system", "content": "Review the bounded evidence. Provide concise risks only. You cannot override test results or execute tools."},
                            {"role": "user", "content": self.diagnostic_context(task, results, diff, "Review final changes")}])
                        if await self.workspace_fingerprint(view) != verified_snapshot:
                            await update("paused", "Workspace changed during model review. Reopen and verify again.")
                            return
                        task = self.runtime.get(plan_id)
                        report = {"goal": goal, "passed": True, "tests": results, "review": review[:8000],
                                  "diff": diff, "workspace": task["workspace"], "branch": task["branch"],
                                  "workspace_fingerprint": verified_snapshot,
                                  "git_approval": "Review Diff and tests, then accept report. Commit/push/merge remain separate explicit Git operations."}
                        await update("awaiting_approval", "Independent validation passed; review report and Git Diff", report=report)
                        return
                    if any(r["category"] in {"environment", "configuration", "permission", "network", "timeout"} for r in results):
                        await update("paused", "Verification environment/configuration/permission/network/timeout issue. Resolve locally and resume; no diagnostic API request sent.")
                        return
                    task = self.runtime.get(plan_id)
                    task["repairs"] += 1
                    self.runtime.save(task)
                    self.runtime.append_repair_step(plan_id)
                    await update("repairing", "Tests or plan incomplete; provide actual failure evidence to Executor")
                    repeated = len(history) >= 2 and history[-1]["fingerprint"] == history[-2]["fingerprint"]
                    if repeated or task["repairs"] >= max(1, task["config"]["budget"]["local_repairs"]) or code == "TOOL_LOOP_DETECTED":
                        advice = await self.escalate(router, task, results, diff, "Repeated failure/no progress" if repeated else "Local repair limit or tool cycle", update)
                await update("failed", "Orchestration safety iteration limit reached")
        except asyncio.CancelledError:
            with suppress(Exception):
                target = self.stop_reasons.pop(plan_id, "cancelled")
                current = self.runtime.get(plan_id)
                current["last_error"] = {"code":"TASK_PAUSED" if target == "paused" else "TASK_CANCELLED"}
                self.runtime.save(current)
                await update(target, "Execution interrupted; checkpoint and uncertain API reservations retained")
            raise
        except (ProviderError, TimeoutError) as exc:
            current = self.runtime.get(plan_id)
            current["last_error"] = {"code":getattr(exc, "code", "TASK_TIMEOUT"), "role":getattr(exc, "role", None), "phase":current["status"]}
            if isinstance(exc, BudgetExceeded) and exc.details:
                current["last_error"]["budget"] = exc.details
            self.runtime.save(current)
            with suppress(Exception):
                await update("paused", redact_text(str(exc), exact_secrets=self.server._exact_secrets()))
        except Exception as exc:
            current = self.runtime.get(plan_id)
            current["last_error"] = {"code":"TASK_INTERNAL_ERROR", "exception_type":type(exc).__name__}
            self.runtime.save(current)
            with suppress(Exception):
                await update("failed", redact_text(str(exc), exact_secrets=self.server._exact_secrets()))
        finally:
            with suppress(Exception):
                self.diagnostics(plan_id)
            self.server.approvals.finish_turn(turn_id)
            self.running.pop(plan_id, None)
            with suppress(Exception):
                status = self.runtime.get(plan_id)["status"]
                event = "turn.completed" if status == "awaiting_approval" else "turn.cancelled" if status in {"paused", "cancelled"} else "turn.failed"
                await emit(event, {"autonomous_task": True, "task_status": status, "reason": self.runtime.get(plan_id)["reason"],
                                   "code": "TASK_" + status.upper(), "message": self.runtime.get(plan_id)["reason"],
                                   "verification": {"complete": status == "awaiting_approval"}})
                await emit("task.updated", {"task": self.public(self.runtime.get(plan_id))})

    def diagnostics(self, plan_id):
        from agent.core.task_diagnostics import export_diagnostics
        return export_diagnostics(self.runtime, plan_id, self.server.store.data_dir / "task-diagnostics", self.server._exact_secrets())

    def diagnostic_context(self, task, results, diff, question):
        # Explicit byte/character bounds and redaction; no repository dump or full logs.
        text = json.dumps({"question": question, "goal": task["goal"][:3000], "diff": diff[:6000],
            "failures": [{"command": r["command"], "category": r["category"], "summary": r.get("summary", "")[-1200:]} for r in results[:6]],
            "attempts": task["attempt_history"][-4:], "planning_failures":task.get("planning_failures", [])[-3:],
            "plan_schema":PLAN_SCHEMA if not task["planned"] else None}, ensure_ascii=False)
        return redact_text(text[:16000], exact_secrets=self.server._exact_secrets(), max_chars=16000)

    async def escalate(self, router, task, results, diff, reason, update):
        if task["config"]["strategy"] == "local-only":
            raise BudgetExceeded("Local repair/no-progress limit reached in local-only mode; API requests disabled")
        await update("escalating", reason)
        advice = await router.text("escalation", [{"role": "system", "content": "Diagnose only. Return concise actionable repair suggestions, never tool calls. Execution remains with the task Executor."},
            {"role": "user", "content": self.diagnostic_context(task, results, diff, "What concrete change resolves this failure, and what test should confirm it?")}])
        current = self.runtime.get(task["id"])
        current["escalations"] += 1
        current["repairs"] = 0
        self.runtime.save(current)
        await update("repairing", "Diagnostic advice received; return control to Executor")
        return advice
