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
from agent.llm.router import ModelRouter, validate_config, apply_config_overrides
from agent.llm.planning import PLAN_PROMPT, PLAN_SCHEMA
from agent.server.protocol import envelope, new_id
from agent.tools.registry import ToolRegistry
from agent.tools.base import ToolError
from agent.tools.workspace import Workspace


def autonomous_git_block(name: str, arguments: dict) -> str:
    if name in {"write_file", "apply_patch"} and ".git" in re.split(r"[/\\]+", str(arguments.get("path", "")).lower()):
        return "Task Git metadata is protected; use the explicit Git workflow."
    if name in {"git_commit", "git_worktree_remove", "git_worktree_create"}:
        return "Autonomous execution stops at Git review; use the explicit Git workflow after reviewing tests and Diff."
    command = str(arguments.get("command", "")) if name in {"run_command", "start_process"} else ""
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
        self.runtime.ledger=server.runtime_ledger
        self.runtime.recover()
        self.running: dict[str, str] = {}
        self.stop_reasons: dict[str, str] = {}
        self.provider_factory_override = None  # Dependency injection for deterministic tests.
        self.credentials = {}  # Memory only; Electron safeStorage owns persistence.
        from agent.core.model_diagnostics import ModelDiagnostics
        self.model_diagnostics = ModelDiagnostics()

    def catalog(self):
        return ModelCatalog(self.server.store, self.server.settings)

    def settings(self) -> dict:
        self.catalog().load()  # Idempotent migration before reading role defaults.
        raw = self.server.store.get_setting("orchestration.config")
        return validate_config(json.loads(raw) if raw else None)

    def vision_binding(self, config, catalog=None):
        pid = config.get('vision_profile_id') if 'vision_profile_id' in config else (config.get('gui_verification') or {}).get('vision_profile_id')
        if not pid:
            return None
        observer = validate_config({'strategy': 'single-agent', 'roles': {'executor': {'model_profile_id': pid}}})
        profile = self.catalog().resolve(observer, catalog)['roles']['executor']
        if config.get('strategy') == 'local-only' and profile['route'] == 'api':
            raise ValueError('Local-only tasks cannot send screenshots to an online observer')
        if not profile.get('supports_vision'):
            raise ValueError('Selected vision observer does not declare image support; use UI Automation or test vision first')
        return profile

    def public(self, task: dict) -> dict:
        return {**task, "usage": self.runtime.usage(task["id"]),
                "calls": self.runtime.calls(task["id"]), "plan": self.runtime.plans.get(task["id"]),
                "checkpoint": self.runtime.plans.latest_checkpoint(task["id"])}

    async def interrupt(self, plan_id: str, target: str, reason="User requested"):
        """Shared stop path for task controls and confirmed conversation deletion."""
        if target not in {"paused", "cancelled"}:
            raise ValueError("Invalid stop target")
        task = self.runtime.get(plan_id)
        if task.get("cleanup_error"):
            raise ValueError("Task process cleanup failed; conversation retained. Inspect Task diagnostics before recovery.")
        turn_id = self.running.get(plan_id)
        running = self.server.active_turns.get(turn_id)
        if running and not running.done():
            if self.stop_reasons.get(plan_id)=='cancelled':target='cancelled'
            self.stop_reasons[plan_id] = target
            self.server.approvals.cancel_turn(turn_id)
            running.cancel()
            try:
                outcomes = await asyncio.wait_for(asyncio.shield(asyncio.gather(running, return_exceptions=True)), 45)
            except TimeoutError as exc:
                raise ValueError("Task shutdown is not complete; conversation retained. Retry after its processes stop.") from exc
            if any(isinstance(outcome, Exception) for outcome in outcomes):
                raise ValueError("Task shutdown failed; conversation retained. Inspect Task diagnostics before recovery.")
            if self.runtime.get(plan_id)["status"] != target:
                self.runtime.transition(plan_id, target, reason)
            self.stop_reasons.pop(plan_id, None)
            self.running.pop(plan_id, None)
        else:
            task["last_error"] = {"code":"TASK_PAUSED" if target == "paused" else "TASK_CANCELLED"}
            self.runtime.save(task)
            self.runtime.transition(plan_id, target, reason)

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
                result = {"catalog": self.catalog().load(), "config": self.settings(), "global_usage":self.runtime.usage(),
                          "chat_default":self.server.store.get_setting('chat.default_profile_id') or '',
                          "chat_vision":self.server.store.get_setting('chat.vision_profile_id') or ''}
                result['model_tests'] = {p['model_profile_id']:self.catalog().test_result(p['model_profile_id']) for p in result['catalog']['profiles']}
            elif kind == "task.catalog.update":
                catalog = validate_catalog(payload.get("catalog"))
                config = validate_config(payload.get("config") or self.settings())
                self.catalog().resolve(config, catalog)  # Reject dangling/disabled role bindings.
                self.vision_binding(config, catalog)
                for field in ('chat_default','chat_vision'):
                    if field in payload and payload[field]:
                        selected = next((p for p in catalog['profiles'] if p['model_profile_id'] == payload[field]), None)
                        if not selected or not next(c for c in catalog['connections'] if c['connection_id'] == selected['connection_id'])['enabled']:
                            raise ValueError(field + ': select an enabled saved profile')
                        if field == 'chat_vision' and not selected.get('supports_vision'):
                            raise ValueError('Vision Observer must declare image input support')
                with self.server.store.connection:
                    for key, value in ((CATALOG_KEY, catalog), ("orchestration.config", config)):
                        self.server.store.connection.execute("INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, json.dumps(value)))
                    for field, key in (('chat_default','chat.default_profile_id'),('chat_vision','chat.vision_profile_id')):
                        if field in payload:
                            if not isinstance(payload[field],str):
                                raise ValueError('Invalid ' + field)
                            self.server.store.connection.execute("INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key,payload[field]))
                result = {"catalog": catalog, "config": config}
                if 'chat_default' in payload:
                    self.server.default_model = 'profile:'+payload['chat_default'] if payload['chat_default'] else None
            elif kind == "task.settings.get":
                result = {"config": self.settings(), "global_usage": self.runtime.usage()}
            elif kind == "task.settings.update":
                if self.server.active_turns:
                    raise ValueError("Pause active execution before changing task settings")
                config = validate_config(payload.get("config"))
                self.catalog().resolve(config)
                self.vision_binding(config)
                self.server.store.set_setting("orchestration.config", json.dumps(config))
                result = {"config": config, "global_usage": self.runtime.usage()}
            elif kind == "task.model.diagnostic.cancel":
                self.model_diagnostics.cancel(payload.get('connection_id'))
                result = {'cancel_requested': True}
            elif kind == "task.model.diagnostic":
                catalog = self.catalog().load()
                profile = next((p for p in catalog['profiles'] if p['model_profile_id'] == payload.get('model_profile_id')), None)
                if not profile:
                    raise ValueError('Select a saved model profile before diagnosis')
                connection = next(c for c in catalog['connections'] if c['connection_id'] == profile['connection_id'])
                if payload.get('connection_id') != connection['connection_id']:
                    raise ValueError('Selected profile does not belong to this connection')
                if not isinstance(payload.get('live', False), bool) or not isinstance(payload.get('vision', True), bool):
                    raise ValueError('Live Test and vision flags must be explicit booleans')
                provider = self.make_provider(asdict(self.server.settings), 'api', {'_connection': connection, 'model': profile['model_id'], 'context_window': profile['context_window'], 'temperature': profile['temperature']})
                result = await self.model_diagnostics.run(provider, connection, profile, live=payload.get('live') is True, vision=payload.get('vision', True))
                result['executor_bound'] = self.settings()['roles']['executor'].get('model_profile_id') == profile['model_profile_id']
                result['model_profile_id'] = profile['model_profile_id']
                result['config_fingerprint'] = self.catalog().fingerprint(profile['model_profile_id'])
                self.server.store.set_setting('model.test.'+profile['model_profile_id'], json.dumps(result))
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
                if kind == 'task.runtime.events':
                    result={'events':self.server.runtime_ledger.events(thread_id=thread_id,after=payload.get('after',0),limit=payload.get('limit',100))}
                    if payload.get('export') is True:
                        path=self.server.store.data_dir/'unified-diagnostics'/('thread-'+hashlib.sha256(thread_id.encode()).hexdigest()[:24]+'.json')
                        path.parent.mkdir(parents=True,exist_ok=True)
                        result['exported_events']=self.server.runtime_ledger.export_run(path,thread_id=thread_id)
                        result['json_path']=str(path)
                elif kind == 'task.runtime.diagnostics':
                    owner=str(payload.get('run_id') or '')
                    if not self.server.store.connection.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='agent_execution_runs'").fetchone():
                        raise ValueError('No unified run exists in this thread')
                    row=self.server.store.connection.execute('SELECT data_json FROM agent_execution_runs WHERE id=? AND thread_id=?',(owner,thread_id)).fetchone()
                    if not row or not json.loads(row[0]).get('unified'):
                        raise ValueError('Unified run not found in this thread')
                    from agent.core.unified_runtime import export_diagnostics
                    result=export_diagnostics(self.server.store.path.parent/'unified-diagnostics',owner,json.loads(row[0]),self.runtime.plans,exact_secrets=self.server._exact_secrets(),ledger=self.server.runtime_ledger)
                elif kind == "task.runtime.list":
                    rows = self.server.store.connection.execute("SELECT id,data_json FROM agent_execution_runs WHERE thread_id=? AND json_type(data_json,'$.unified')='object' ORDER BY json_extract(data_json,'$.unified.updated_at') DESC,rowid DESC LIMIT 1",(thread_id,)).fetchall() if self.server.store.connection.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='agent_execution_runs'").fetchone() else []
                    runtimes=[]
                    for row in rows:
                        runtime=json.loads(row['data_json']).get('unified')
                        if runtime:
                            value={**runtime,'id':row['id']}
                            if value.get('plan_id'):
                                from agent.core.unified_runtime import plan_view
                                value['plan']=plan_view(self.runtime.plans.get(value['plan_id']))
                            runtimes.append(value)
                    result={'runtimes':runtimes,'active_turn_ids':[tid for tid,turn in self.server.active_turns.items() if not turn.done() and self.server.active_turn_threads.get(tid)==thread_id and tid not in self.server.disconnected_turns]}
                elif kind == "task.list":
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
                    vision_binding = self.vision_binding(config)
                    if any(p for p in self.runtime.plans.list_for_thread(thread_id)
                           if self.runtime.plans.active_step(p["id"]) and not self.runtime.db.execute(
                               "SELECT 1 FROM autonomous_tasks WHERE plan_id=?", (p["id"],)).fetchone()):
                        raise ValueError("Finish or use a new thread for the existing manual plan")
                    task = self.runtime.create(thread_id, goal, config, str(project.workspace.root))
                    task["provider_settings"] = asdict(self.server.settings)  # No keys in settings.
                    task['entrypoint'] = 'conversation' if payload.get('entrypoint') == 'conversation' else 'advanced'
                    task["resolved_roles"] = resolved["roles"]
                    task['resolved_vision'] = vision_binding
                    task['catalog_snapshot'] = self.catalog().load()
                    task["global_budget"] = saved["budget"]
                    task["config_source"] = config_source
                    task["config_snapshot_at"] = time.time()
                    self.runtime.save(task)
                    if task.get('entrypoint') == 'conversation':
                        project.state.append_message(thread_id,role='user',content=goal)
                    result = {"task": self.public(task), "defaults":saved, "catalog":self.catalog().load(), "global_usage":self.runtime.usage()}
                    await ws.send_json(envelope("task.loaded", result, request_id=request_id, thread_id=thread_id))
                    self.launch(ws, task, project, owned_turns)
                    return
                else:
                    task = self.runtime.get(str(payload.get("task_id") or ""))
                    if task["thread_id"] != thread_id:
                        raise ValueError("Task belongs to another thread")
                    plan_id = task["id"]
                    if kind=='task.append':
                        running=self.server.active_turns.get(self.running.get(plan_id))
                        if task['status'] not in {'planning','executing','repairing','verifying','escalating'} or not running or running.done() or plan_id in self.stop_reasons:
                            raise ValueError('当前 Task 已停止，追加内容尚未发送模型')
                        self.server.enqueue_followup(project,plan_id,thread_id,payload.get('message_id'),payload.get('prompt'))
                        await ws.send_json(envelope('task.loaded',{'task':self.public(task),'followup':{'message_id':payload['message_id'],'queued':True,'boundary':'完整工具批次结束后的模型请求前'}},request_id=request_id,thread_id=thread_id))
                        return
                    if kind in {"task.pause", "task.cancel"}:
                        await self.interrupt(plan_id, "paused" if kind == "task.pause" else "cancelled")
                    elif kind in {"task.resume", "task.continue"}:
                        if kind == 'task.continue' and payload.get('followup_id') in task.get('followup_ids',[]):
                            await ws.send_json(envelope('task.loaded', {'task':self.public(task)},request_id=request_id,thread_id=thread_id))
                            return
                        if kind == 'task.continue' and (not isinstance(payload.get('prompt'),str) or not 1 <= len(payload['prompt'].strip()) <= 4000):
                            raise ValueError('Follow-up must contain 1..4000 characters')
                        if kind == 'task.continue':
                            if not isinstance(payload.get('followup_id'),str) or not 1 <= len(payload['followup_id']) <= 100:
                                raise ValueError('Follow-up identifier required')
                            if len(task['goal'])+len(payload['prompt'].strip())+12 > 32000 or len(task.get('followup_ids',[])) >= 32 or len(self.runtime.plans.get(plan_id)['steps']) >= 100:
                                raise ValueError('Conversation task continuation limit reached; review and start a new development session')
                        if payload.get("local_only") is True and task["config"]["strategy"] == "single-agent":
                            raise ValueError("Single Agent requires an online Executor; explicitly configure another strategy to switch modes")
                        if any(not t.done() for t in self.server.active_turns.values()):
                            raise ValueError("Stop the active task first")
                        if payload.get("confirm_workspace") is not True:
                            raise ValueError("Review workspace and checkpoint, then explicitly confirm recovery")
                        if task["status"] not in {"paused", "failed", "cancelled", "completed", "awaiting_approval"}:
                            raise ValueError("Task cannot be resumed in its current state")
                        if task["status"] != "paused":
                            self.runtime.transition(plan_id, "paused", "User reopened task")
                        task = self.runtime.get(plan_id)
                        if kind == 'task.continue':
                            if not self.runtime.append_followup(plan_id,payload.get('prompt'),payload.get('followup_id')):
                                await ws.send_json(envelope('task.loaded', {'task':self.public(self.runtime.get(plan_id))},request_id=request_id,thread_id=thread_id))
                                return
                            task = self.runtime.get(plan_id)
                            if payload.get('entrypoint') == 'conversation' or task.get('entrypoint') == 'conversation':
                                task['entrypoint'] = 'conversation'
                                self.runtime.save(task)
                                project.state.append_message(thread_id,role='user',content=payload['prompt'].strip())
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
                        task['resolved_vision'] = self.vision_binding(task['config'])
                        task['catalog_snapshot'] = self.catalog().load()
                        task["global_budget"] = self.settings()["budget"]
                        task["provider_settings"] = asdict(self.server.settings)
                        task["config_source"] = "paused-task-configuration"
                        task["config_snapshot_at"] = time.time()
                        task.pop("resolved_verification_commands", None)
                        task.pop('resolved_gui_verification', None)
                        task.pop('acceptance_baseline', None)
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
                provider = OllamaProvider(**kwargs)
                provider.supports_vision = profile.get('supports_vision',False)
                return provider
            ref = connection["credential_reference"]
            key = self.server.openai_api_key if ref == "legacy-openai" else self.credentials.get(ref, "")
            provider = OpenAICompatibleProvider(**kwargs, api_key=key or "")
            provider.supports_vision = profile.get('supports_vision',False)
            return provider
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
        if self.runtime.get(task['id'])['status']=='cancelled':
            raise ValueError('取消已生效，不能由迟到的恢复请求启动 Task')
        turn_id = new_id("turn")
        self.running[task["id"]] = turn_id
        owned_turns.add(turn_id)
        running = asyncio.create_task(self.run(ws, task["id"], project, turn_id), name=turn_id)
        self.server.active_turns[turn_id] = running
        self.server.active_turn_threads[turn_id] = task["thread_id"]
        running.add_done_callback(lambda _: self.server.forget_turn(turn_id))

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
        single = task["config"]["strategy"] == "single-agent"
        task.pop("last_error", None)
        self.runtime.save(task)
        thread_id, goal = task["thread_id"], task["goal"]
        async def emit(kind, payload):
            await ws.send_json(envelope(kind, payload, thread_id=thread_id, turn_id=turn_id))
        async def update(status, reason="", **values):
            if status in {'paused','failed','cancelled'} and 'report' not in values:
                current = self.runtime.get(plan_id)
                diff = ''
                if 'workspace' in current and current['workspace']:
                    with suppress(Exception):
                        result = await view.tools.execute('git_diff', {})
                        diff = redact_text(result.stdout, exact_secrets=self.server._exact_secrets())
                actual = values.get('verification', current.get('verification',[]))
                gui_result = next((r for r in actual if r.get('command')=='GUI acceptance'),None)
                values['report'] = {'goal':goal,'passed':False,'tests':actual,
                    'gui_verification':('PASS' if gui_result['ok'] else 'FAIL') if gui_result else 'NOT RUN',
                    'review':'任务未完成：'+reason, 'diff':diff,'unfinished':[reason], 'workspace':current.get('workspace')}
            self.runtime.transition(plan_id, status, reason, **values)
            await emit("task.updated", {"task": self.public(self.runtime.get(plan_id))})
        try:
            await emit("turn.started", {"prompt": goal, "model": "Single Agent" if single else "Task router", "provider": task["config"]["strategy"], "project_id": source.id})
            remaining = task["config"]["budget"]["task_seconds"] - task["elapsed_seconds"]
            if remaining <= 0:
                raise BudgetExceeded("Task execution time exhausted; explicitly add time before recovery")
            async with asyncio.timeout(remaining):
                if single and not task["planned"]:
                    # Bookkeeping only: no Planner request or structured-model contract.
                    self.runtime.replace_unstarted_steps(plan_id, [{"description": goal[:4000]}])
                    task["planned"] = True
                    self.runtime.save(task)
                await update("planning" if not task["planned"] else "executing", "Inspect workspace before resuming; completed mutations are not replayed", report={})
                budget = BudgetGuard(self.runtime, plan_id, task["global_budget"] if "global_budget" in task else self.settings()["budget"])
                router = ModelRouter(task["config"], lambda route, profile: self.make_provider(task["provider_settings"], route, profile), budget, emit, task.get("resolved_roles"),retry_attempts=self.server.model_retry_attempts)
                # Validate the task's frozen routes before worktree approval or HTTP.
                single_provider = None
                for role in (("executor",) if single else ("planner", "executor", "reviewer")):
                    resolved_provider = router.resolve(role)
                    if single:
                        single_provider = resolved_provider
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
                from agent.core.verification import acceptance_snapshot, acceptance_changes
                if 'acceptance_baseline' not in task:
                    task['acceptance_baseline'] = acceptance_snapshot(view.workspace.root)
                    self.runtime.save(task)
                if 'resolved_gui_verification' not in task:
                    from agent.core.gui_verification import discover_gui
                    gui = discover_gui(view.workspace.root, task['config'].get('gui_verification'))
                    task['resolved_gui_verification'] = gui
                    task['resolved_vision'] = self.vision_binding({**task['config'], 'gui_verification': gui}, task.get('catalog_snapshot'))
                    self.runtime.save(task)
                async def execute(name, arguments, on_raw_output=None, environment=None):
                    return await self.server._authorize_tool(ws, project=view, call=ToolCall(name, arguments),
                        call_id=new_id("verification"), thread_id=thread_id, turn_id=turn_id,
                        user_prompt=goal, autonomous=True, on_raw_output=on_raw_output, environment=environment,
                        supports_vision=bool(task.get('resolved_vision')),
                        desktop_destination={'model_id': task['resolved_vision']['model'],
                                             'connection': task['resolved_vision'].get('_connection', {}).get('display_name')} if task.get('resolved_vision') else None)
                verifier = VerificationEngine(self.server.store.data_dir / "verification" / plan_id, execute, task["config"]["budget"]["verification_seconds"])
                advice = ""
                # A fixed safety bound supplements configurable time and API limits.
                for _ in range(200):
                    task = self.runtime.get(plan_id)
                    goal=task['goal']
                    if not task["planned"]:
                        limit = task["config"]["budget"].get("planning_attempts", 4)
                        if task.get("planning_attempts", 0) >= limit:
                            raise ProviderError("PLAN_RETRY_LIMIT", "Planning attempt limit reached; inspect Task diagnostics before changing the paused task configuration")
                        task["planning_attempts"] = task.get("planning_attempts", 0) + 1
                        self.runtime.save(task)
                        try:
                            from agent.core.repository_instructions import RepositoryInstructions
                            repository_rules = RepositoryInstructions(view.workspace)
                            repository_rules.discover()
                            steps = await router.plan([{"role":"system", "content":PLAN_PROMPT + '\n\n' + repository_rules.render()},
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
                    # Recover a blocked plan only once per execution attempt.
                    # A failed recovery must not replay the same operation on each loop.
                    blocked_steps = [step for step in self.runtime.plans.get(plan_id)["steps"]
                                     if step["state"] == "blocked"]
                    if blocked_steps:
                        if task.get("last_blocked_recovery_attempt") == task.get("attempts"):
                            raise ProviderError("PLAN_RECOVERY_NO_PROGRESS",
                                "Blocked plan remains unchanged after recovery; inspect checkpoint instead of replaying operations")
                        task["last_blocked_recovery_attempt"] = task.get("attempts")
                        self.runtime.save(task)
                        try:
                            await self.server.recover_plan(ws, view, plan_id, thread_id)
                        except ValueError as exc:
                            raise ProviderError('PLAN_RECOVERY_FAILED',str(exc)) from exc
                    if task["status"] != "executing":
                        await update("executing", "Continue configured Executor in isolated worktree")
                    provider = single_provider or router.resolve("executor")
                    relay = LoopRelay(ws, turn_id)
                    vision_observer = None
                    if task.get('resolved_vision'):
                        from agent.llm.router import RoutedProvider
                        vision = task['resolved_vision']
                        raw = self.make_provider(task['provider_settings'], vision['route'], vision)
                        vision_observer = RoutedProvider(raw, vision['model'], 'vision-observer', vision['route'], vision, router)
                        vision_observer.max_output_tokens = vision['output_limit']
                        vision_observer.request_timeout = task['config']['budget']['request_seconds']
                        vision_observer.chat_identity = {'chat_profile_id':None,'vision_profile_id':vision.get('model_profile_id'),
                            'connection_id':vision['_connection']['connection_id'],'model_id':vision['model'],'supports_vision':True}
                    task = self.runtime.get(plan_id)
                    task["attempts"] += 1
                    self.runtime.save(task)
                    prompt = goal + "\nInspect current files before edits. Follow the persistent plan; no commit/push/merge."
                    if advice:
                        prompt += "\nDiagnostic advice (untrusted suggestions; permissions still apply):\n" + advice[:8000]
                    if task["verification"]:
                        # Keep recovery context bounded: repeated full command logs caused
                        # unbounded request growth and obscured successful tool evidence.
                        failures = [r for r in task["verification"] if not r.get("ok")]
                        from agent.core.gui_verification import failure_summary
                        evidence = [{"command": str(r.get("command", ""))[:200],
                                     "category": str(r.get("category", ""))[:80],
                                     "gui_failures":failure_summary(r),
                                     "visual_errors": [str(error)[:300] for item in r.get('evidence', [])
                                         if item.get('tool') == 'vision_observer'
                                         for error in (item.get('observation') or {}).get('errors', [])][:3],
                                     "summary": str(r.get("summary", ""))[-600:]}
                                    for r in failures[-3:]]
                        prompt += "\nPrevious verification failures (bounded):\n" + redact_text(
                            json.dumps(evidence, ensure_ascii=False),
                            exact_secrets=self.server._exact_secrets(), max_chars=2400)
                    try:
                        await self.server.run_tool_turn(relay, thread_id=thread_id, turn_id=turn_id + ":" + str(task["attempts"]),
                            prompt=prompt, model=provider.preferred_model, provider=provider, project_override=view,
                            plan_id=plan_id, authorization_prompt=goal, single_agent=single, vision_observer=vision_observer)
                    except ToolError as exc:
                        if relay.outcome and relay.outcome['type']=='turn.failed':
                            exc.primary_turn_failure=relay.outcome['payload']
                        raise
                    outcome = relay.outcome or {"type": "turn.failed", "payload": {"code": "INTERRUPTED", "message": "Loop interrupted"}}
                    code = outcome["payload"].get("code", "")
                    if (single and outcome['type'] != 'turn.completed') or code in {"BUDGET_EXHAUSTED", "MODEL_TIMEOUT", "OLLAMA_UNAVAILABLE", "OLLAMA_STREAM_FAILED", "OPENAI_COMPATIBLE_AUTH_FAILED", "OPENAI_COMPATIBLE_RATE_LIMITED", "OPENAI_COMPATIBLE_STREAM_FAILED"}:
                        failure = outcome['payload']
                        error = (BudgetExceeded(failure.get('message',code),failure.get('budget')) if code == 'BUDGET_EXHAUSTED'
                                 else ProviderError(code or 'SINGLE_AGENT_INTERRUPTED',failure.get('message','Single Agent did not complete; inspect diagnostics')))
                        error.role = failure.get('role') or getattr(error,'role',None)
                        if isinstance(failure.get('context'),dict):
                            error.context_details = failure['context']
                        raise error
                    await update("verifying", "Run commands directly, without model Tokens")
                    weakened = acceptance_changes(view.workspace.root, task['acceptance_baseline'])
                    if weakened:
                        await update('paused','现有验收文件或测试脚本被修改，需要检查 Diff；未运行被削弱的测试。',
                                     last_error={'code':'ACCEPTANCE_CONTRACT_CHANGED','phase':'verifying','files':weakened[:20]},
                                     verification=[{'command':'acceptance contract','ok':False,'category':'configuration','exit_code':None,'duration_ms':0,'summary':'Protected acceptance changed: '+', '.join(weakened[:20])}])
                        return
                    before_validation = await self.workspace_fingerprint(view)
                    results = await verifier.run(commands)
                    if task.get('resolved_gui_verification') and all(r['ok'] for r in results):
                        from agent.core.gui_verification import run_gui
                        async def observe(message):
                            if not message:
                                raise ProviderError('VISION_IMAGE_MISSING', 'No authorized pixels available')
                            from agent.llm.router import RoutedProvider
                            profile = task['resolved_vision']
                            route = profile['route']
                            raw = self.make_provider(task['provider_settings'], route, profile)
                            observer = RoutedProvider(raw, profile['model'], 'vision-observer', route, profile, router)
                            from agent.core.gui_verification import observe_pixels
                            return await observe_pixels(observer,message,emit)
                        results.append(await run_gui(task['resolved_gui_verification'], execute, view.tools, turn_id,
                                                     observe if task.get('resolved_vision') else None, emit))
                    for result in results:
                        for field in ("stdout", "stderr", "summary"):
                            if field in result:
                                result[field] = redact_text(str(result[field]), exact_secrets=self.server._exact_secrets(), max_chars=5000)
                        if 'evidence' in result:
                            def clean_evidence(value):
                                if isinstance(value, str):
                                    return redact_text(value, exact_secrets=self.server._exact_secrets(), max_chars=5000)
                                if isinstance(value, list):
                                    return [clean_evidence(v) for v in value]
                                if isinstance(value, dict):
                                    # Artifact paths are generated internally, and must remain
                                    # usable locally just like M3 ToolResult paths.
                                    return {k:v if k == 'path' else clean_evidence(v) for k,v in value.items()}
                                return value
                            result['evidence'] = clean_evidence(result['evidence'])
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
                    # A plan advancing through successful steps is progress even
                    # when the resulting code/tests have not changed. Conversely,
                    # passing tests must not hide an unchanged unfinished plan.
                    plan_state = [(s['id'],s['state']) for s in current_plan['steps']]
                    plan_fingerprint = hashlib.sha256(json.dumps([fingerprint,plan_state],sort_keys=True).encode()).hexdigest()
                    task = self.runtime.get(plan_id)
                    previous_history = task['attempt_history']
                    history = [*previous_history, {"fingerprint": fingerprint, 'plan_fingerprint':plan_fingerprint,
                        "reason": code or "verification", "attempt": task["attempts"]}][-30:]
                    task.update(verification=results, attempt_history=history)
                    # Keep persisted history bounded too: command output and nested
                    # evidence may otherwise grow on every pause/resume cycle.
                    # Preserve complete evidence locally before reducing the UI
                    # snapshot. Screenshot identities are required for GUI audit.
                    archive = self.server.store.data_dir / 'verification' / plan_id / ('attempt-' + str(task['attempts']) + '-' + str(time.time_ns()) + '.json')
                    archive.parent.mkdir(parents=True, exist_ok=True)
                    def clean_history(value):
                        if isinstance(value, str):
                            return redact_text(value, exact_secrets=self.server._exact_secrets(), max_chars=len(value))
                        if isinstance(value, list): return [clean_history(v) for v in value]
                        if isinstance(value, dict): return {k:clean_history(v) for k,v in value.items()}
                        return value
                    archive.write_text(json.dumps(clean_history(results), ensure_ascii=False), encoding='utf-8')
                    compact_results = [
                        {"command": str(r.get("command", ""))[:200],
                         "ok": bool(r.get("ok")), "category": str(r.get("category", ""))[:80],
                         "exit_code":r.get('exit_code'), "log_path":r.get('log_path'),
                         "evidence":[{k:v for k,v in e.items() if k in {'tool','ok','path','artifact_id','sha256'}} for e in r.get('evidence',[])[:64]],
                         "summary": str(r.get("summary", ""))[-600:]}
                        for r in results[:12]
                    ]
                    task['verification_history'] = [*task.get('verification_history', []),
                        {'attempt': task['attempts'], 'passed': bool(passed), 'history_path':str(archive),
                         'at': time.time(), 'results': compact_results}][-10:]
                    self.runtime.save(task)
                    await emit("verification.completed", {"results": results, "passed": bool(passed)})
                    if self.server.runtime_ledger.pending(plan_id) and outcome['type']=='turn.completed':
                        await update('repairing','追加需求将在下一次模型请求前生效；保留已完成步骤')
                        continue
                    if passed:
                        review = "Single Agent completed; independent commands and Git Diff passed. Review the evidence below." if single else await router.text("reviewer", [{"role": "system", "content": "Review the bounded evidence. Provide concise risks only. You cannot override test results or execute tools."},
                            {"role": "user", "content": self.diagnostic_context(task, results, diff, "Review final changes")}])
                        if await self.workspace_fingerprint(view) != verified_snapshot:
                            await update("paused", "Workspace changed during model review. Reopen and verify again.")
                            return
                        task = self.runtime.get(plan_id)
                        if self.server.runtime_ledger.pending(plan_id):
                            await update('repairing','审查期间收到追加需求，继续原任务')
                            continue
                        report = {"goal": task['goal'], "passed": True, "tests": results, "review": review[:8000],
                                  'unfinished': [],
                                  'gui_verification': 'PASS' if task.get('resolved_gui_verification') else 'NOT RUN',
                                  "diff": diff, "workspace": task["workspace"], "branch": task["branch"],
                                  "workspace_fingerprint": verified_snapshot,
                                  "git_approval": "Review Diff and tests, then accept report. Commit/push/merge remain separate explicit Git operations."}
                        await update("awaiting_approval", "Independent validation passed; review report and Git Diff", report=report)
                        return
                    blocking_categories = {"environment", "configuration", "permission", "network", "timeout"}
                    blocking_results = [r for r in results if not r.get("ok") and r.get("category") in blocking_categories]
                    if blocking_results:
                        # Preserve the precise failing command in persistent task state.
                        # A generic pause reason hid the actionable error for 87 resumes.
                        first = blocking_results[0]
                        failure = {
                            "code": "VERIFICATION_" + str(first.get("category", "unknown")).upper(),
                            "phase": "verifying",
                            "command": str(first.get("command", ""))[:300],
                            "category": str(first.get("category", ""))[:80],
                            "exit_code": first.get("exit_code"),
                            "summary": str(first.get("summary", ""))[-1200:],
                            "log_path": str(first.get("log_path", ""))[:500],
                            "failed_count": len(blocking_results),
                        }
                        task = self.runtime.get(plan_id)
                        task["last_error"] = failure
                        self.runtime.save(task)
                        await update("paused",
                            "Verification blocked: " + failure["category"] + " in " +
                            (failure["command"] or "(no command)") + "; " +
                            failure["summary"][-300:])
                        return
                    if all(r['ok'] for r in results) and diff_result.get('ok') and not plan_complete:
                        # A prior identical checkpoint means another Executor turn would
                        # replay already-applied plan operations. Fail closed instead.
                        if previous_history and previous_history[-1].get('plan_fingerprint') == plan_fingerprint:
                            error = ProviderError('TASK_PLAN_NO_PROGRESS',
                                'Independent commands passed, but the same plan steps remain unfinished. '
                                'Stopped before another model request; inspect the current step verification and actual tool evidence.')
                            error.context_details = {'completed_steps':sum(s['state']=='completed' for s in current_plan['steps']),
                                'remaining_steps':sum(s['state']!='completed' for s in current_plan['steps']),
                                'verification_passed':True,'request_sent':False}
                            raise error
                        # Continue the existing plan, not a new repair step or a
                        # paid diagnosis of tests that are already passing.
                        advice = 'Independent commands passed. Finish ONLY the current remaining plan step with fresh tool evidence; do not redo completed edits.'
                        await update('repairing','Independent commands passed; continue the remaining plan without paid escalation')
                        continue
                    task = self.runtime.get(plan_id)
                    task["repairs"] += 1
                    self.runtime.save(task)
                    self.runtime.append_repair_step(plan_id)
                    await update("repairing", "Tests or plan incomplete; provide actual failure evidence to Executor")
                    repeated = len(history) >= 2 and history[-1]["fingerprint"] == history[-2]["fingerprint"]
                    if single:
                        if repeated or task["repairs"] > task["config"]["budget"]["local_repairs"]:
                            raise ProviderError("SINGLE_AGENT_NO_PROGRESS" if repeated else "SINGLE_AGENT_REPAIR_LIMIT", "Independent verification still fails; bounded single-model repair stopped")
                        advice = "Repair the actual independent verification failures using the same model and real tools."
                        continue
                    if repeated or task["repairs"] >= max(1, task["config"]["budget"]["local_repairs"]) or code == "TOOL_LOOP_DETECTED":
                        diagnosed = task.get('diagnosed_failure_fingerprints',[])
                        if fingerprint in diagnosed:
                            raise ProviderError('REPAIR_NO_PROGRESS','The same failure and Diff persisted after model diagnosis. Stopped before another diagnosis request; checkpoint and evidence retained.')
                        advice = await self.escalate(router, task, results, diff, "Repeated failure/no progress" if repeated else "Local repair limit or tool cycle", update)
                        task = self.runtime.get(plan_id)
                        task['diagnosed_failure_fingerprints'] = [*diagnosed,fingerprint][-30:]
                        self.runtime.save(task)
                await update("failed", "Orchestration safety iteration limit reached")
        except asyncio.CancelledError:
            with suppress(Exception):
                target = self.stop_reasons.pop(plan_id, "cancelled")
                current = self.runtime.get(plan_id)
                current["last_error"] = {"code":"TASK_PAUSED" if target == "paused" else "TASK_CANCELLED"}
                self.runtime.save(current)
                await update(target, "Execution interrupted; checkpoint and uncertain API reservations retained")
            raise
        except (ProviderError, ToolError, TimeoutError) as exc:
            current = self.runtime.get(plan_id)
            current["last_error"] = {"code":getattr(exc, "code", "TASK_TIMEOUT"), "role":getattr(exc, "role", None), "phase":current["status"]}
            if isinstance(exc, BudgetExceeded) and exc.details:
                current["last_error"]["budget"] = exc.details
            if isinstance(getattr(exc,'context_details',None),dict):
                current['last_error']['context'] = exc.context_details
            primary=getattr(exc,'primary_turn_failure',None)
            message=str(exc)
            if isinstance(primary,dict):
                current['last_error']['cleanup']={'code':getattr(exc,'code','PROCESS_CLEANUP_FAILED'),
                    'message':redact_text(message,exact_secrets=self.server._exact_secrets())}
                current['last_error']['code']=primary.get('code') or 'TURN_FAILED'
                message=str(primary.get('message') or current['last_error']['code'])+'; cleanup: '+message
            self.runtime.save(current)
            with suppress(Exception):
                await update("paused", redact_text(message, exact_secrets=self.server._exact_secrets()))
        except Exception as exc:
            current = self.runtime.get(plan_id)
            current["last_error"] = {"code":"TASK_INTERNAL_ERROR", "exception_type":type(exc).__name__}
            self.runtime.save(current)
            with suppress(Exception):
                await update("failed", redact_text(str(exc), exact_secrets=self.server._exact_secrets()))
        finally:
            cleanup_error = None
            if 'view' in locals():
                try:
                    await view.tools.desktop.close_owner(turn_id)
                    await view.tools.processes.close_owner(turn_id)
                except Exception as exc:
                    cleanup_error = exc
                    current = self.runtime.get(plan_id)
                    current["cleanup_error"] = {"code":getattr(exc, "code", "PROCESS_CLEANUP_FAILED"), "exception_type":type(exc).__name__}
                    current["last_error"] = current["cleanup_error"]
                    self.runtime.save(current)
                    self.runtime.transition(plan_id, "paused", "Owned process cleanup failed; inspect Task diagnostics before recovery")
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
            if cleanup_error:
                raise cleanup_error

    def diagnostics(self, plan_id):
        from agent.core.task_diagnostics import export_diagnostics
        return export_diagnostics(self.runtime, plan_id, self.server.store.data_dir / "task-diagnostics", self.server._exact_secrets())

    def diagnostic_context(self, task, results, diff, question):
        # Explicit byte/character bounds and redaction; no repository dump or full logs.
        from agent.core.gui_verification import failure_summary
        text = json.dumps({"question": question, "goal": task["goal"][:3000], "diff": diff[:6000],
            "failures": [{"command": r["command"], "category": r["category"], "summary": r.get("summary", "")[-1200:],"gui_failures":failure_summary(r)} for r in results[:6]],
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
