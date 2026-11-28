"""Workspace and acceptance services for tasks executed by Electron's OpenCode runtime."""
import math
from pathlib import Path
import time

from agent.core.diagnostics import redact_text
from agent.core.gui_verification import discover_gui, run_gui
from agent.core.verification import VerificationEngine, acceptance_changes, acceptance_snapshot, discover_commands
from agent.llm.base import ToolCall
from agent.server.protocol import envelope, new_id
from agent.core.budget import BudgetExceeded, check_api_scope


async def prepare_task(service, ws, project, thread_id, payload):
    runtime = service.runtime
    task_id = payload.get("task_id")
    if task_id:
        task = runtime.get(task_id)
        if task["thread_id"] != thread_id or Path(task["source"]).resolve() != project.workspace.root:
            raise ValueError("Task belongs to another workspace")
        if payload.get("confirm_workspace") is not True:
            raise ValueError("Confirm workspace recovery before continuing")
        if task["status"] not in {"pending", "paused", "failed", "cancelled", "awaiting_approval", "completed"}:
            raise ValueError("Task is active")
    else:
        from agent.llm.router import apply_config_overrides, validate_config
        goal = str(payload.get("goal", "")).strip()
        if not 1 <= len(goal) <= 16000:
            raise ValueError("Task goal must contain 1..16000 characters")
        defaults = service.settings()
        config = (validate_config(payload["config"]) if "config" in payload
                  else apply_config_overrides(defaults, payload.get("config_overrides", {})))
        task = runtime.create(thread_id, goal, config, str(project.workspace.root))
        task_id = task["id"]
        task["global_budget"] = defaults["budget"]

    if task["config"]["strategy"] == "local-only" or payload.get("local_only") is True:
        task["opencode_local_only"] = True
    task["engine"] = "opencode"
    runtime.save(task)
    owner = new_id("opencode_worktree")
    try:
        if not task["workspace"]:
            result = await service.server._authorize_tool(
                ws, project=project, call=ToolCall("git_worktree_create", {
                    "task_name": "task-" + task_id[:12], "branch": "lca/task-" + task_id[:12],
                }), call_id=owner, thread_id=thread_id, turn_id=owner,
                user_prompt="Create an isolated task worktree. " + task["goal"],
            )
            if not result.get("ok"):
                raise ValueError("Managed worktree unavailable or approval denied")
            task.update(workspace=result["data"]["path"], branch=result["data"]["branch"])
            runtime.save(task)
        view = await managed_workspace(service, task, project)
        if "resolved_verification_commands" not in task:
            task["resolved_verification_commands"] = discover_commands(view.workspace.root, task["config"]["verification_commands"])
        if "acceptance_baseline" not in task:
            task["acceptance_baseline"] = acceptance_snapshot(view.workspace.root)
        if "resolved_gui_verification" not in task:
            task["resolved_gui_verification"] = discover_gui(view.workspace.root, task["config"].get("gui_verification"))
        if not task["planned"]:
            runtime.replace_unstarted_steps(task_id, [{"description": task["goal"][:4000]}])
            task["planned"] = True
        task["attempts"] += 1
        runtime.save(task)
        if task["status"] not in {"pending", "paused"}:
            runtime.transition(task_id, "paused", "用户已确认恢复工作区")
        return runtime.transition(task_id, "executing", "由 OpenCode 执行隔离工作区任务")
    except (ValueError, OSError, TimeoutError):
        if runtime.get(task_id)["status"] == "pending":
            runtime.transition(task_id, "paused", "工作区准备未完成")
        raise
    finally:
        service.server.approvals.finish_turn(owner)


async def managed_workspace(service, task, project):
    view = service.task_project(task, project)
    listing = await project.tools.execute("git_worktree_list", {})
    if not listing.ok or not any(row.get("managed") and Path(row["path"]).resolve() == view.workspace.root
                                 for row in listing.data.get("worktrees", [])):
        raise ValueError("Task directory is not a managed worktree of the project")
    return view


def reserve_online_request(service, thread_id, payload):
    """Persist a conservative online reservation before the gateway dispatches."""
    runtime = service.runtime
    saved = service.settings()["budget"]
    task_id = payload.get("task_id")
    if task_id:
        task = runtime.get(task_id)
        if task["thread_id"] != thread_id or task.get("engine") != "opencode" or task["status"] != "executing":
            raise ValueError("Online reservation requires an active owned task")
        limits = task["config"]["budget"]
        global_limits = task.get("global_budget", saved)
        owner = task_id
        elapsed = task["elapsed_seconds"] + max(0, time.time() - task["active_since"])
        if elapsed >= limits["task_seconds"]:
            raise BudgetExceeded("Task execution time exhausted")
    else:
        turn = payload.get("turn_id", "")
        if not isinstance(turn, str) or not turn.startswith("turn_") or len(turn) != 37:
            raise ValueError("Invalid turn owner")
        owner, limits, global_limits = thread_id + ":" + turn, saved, saved
    profile_id = payload.get("profile_id")
    catalog = service.catalog().load()
    profile = next((row for row in catalog["profiles"] if row["model_profile_id"] == profile_id), None)
    connection = next((row for row in catalog["connections"] if profile and row["connection_id"] == profile["connection_id"]), None)
    if not connection or not connection["enabled"] or connection["provider_type"] != "openai_compatible":
        raise ValueError("Selected online connection is no longer enabled")
    input_bytes, output = payload.get("input_bytes"), payload.get("max_output")
    if type(input_bytes) is not int or not 1 <= input_bytes <= 2_000_000 or type(output) is not int or not 1 <= output <= 262144:
        raise ValueError("Invalid online reservation")
    pricing = profile.get("pricing") or {}
    if (limits["api_cost"] is not None or global_limits["global_api_cost"] is not None) and (
        pricing.get("input_price") is None or pricing.get("output_price") is None
    ):
        raise BudgetExceeded("Cost cap requires configured input and output prices")
    input_tokens = input_bytes + 256
    tokens = input_tokens + output
    cost = (input_tokens * (pricing.get("input_price") or 0) + output * (pricing.get("output_price") or 0)) / 1_000_000
    if not math.isfinite(cost):
        raise BudgetExceeded("Configured prices overflow the request cost estimate")
    db = runtime.db
    db.execute("""CREATE TABLE IF NOT EXISTS opencode_model_reservations
        (id TEXT PRIMARY KEY, owner TEXT NOT NULL, reserved_tokens INTEGER NOT NULL, reserved_cost REAL NOT NULL)""")
    db.execute("BEGIN IMMEDIATE")
    try:
        check_api_scope(scope="task", caps=limits, used=runtime.usage(owner), tokens=tokens, cost=cost, context={})
        check_api_scope(scope="global", caps=global_limits, used=runtime.usage(), tokens=tokens, cost=cost, context={})
        db.execute("INSERT INTO opencode_model_reservations VALUES(?,?,?,?)", (new_id("oc_req"), owner, tokens, cost))
        db.commit()
    except BaseException:
        db.rollback()
        raise


async def finish_task(service, ws, project, thread_id, payload):
    runtime = service.runtime
    task = runtime.get(payload["task_id"])
    task_id = task["id"]
    if task["thread_id"] != thread_id or task.get("engine") != "opencode" or task["status"] != "executing":
        raise ValueError("OpenCode task execution state does not match")
    outcome = payload.get("outcome")
    if outcome != "succeeded":
        status = "cancelled" if outcome == "cancelled" else "paused"
        return runtime.transition(task_id, status, "OpenCode 执行未完成，保留工作区")
    runtime.transition(task_id, "verifying", "执行独立验收命令")
    owner = new_id("opencode_verify")
    view = None
    try:
        view = await managed_workspace(service, task, project)
        changed = acceptance_changes(view.workspace.root, task.get("acceptance_baseline", {}))
        if changed:
            return runtime.transition(task_id, "paused", "现有验收契约已修改，等待审阅")

        async def execute(name, arguments, **options):
            return await service.server._authorize_tool(
                ws, project=view, call=ToolCall(name, arguments), call_id=new_id("verification"),
                thread_id=thread_id, turn_id=owner, user_prompt=task["goal"], autonomous=True, **options,
            )

        verifier = VerificationEngine(service.server.store.data_dir / "verification" / task_id, execute,
                                      task["config"]["budget"]["verification_seconds"])
        before = await service.workspace_fingerprint(view)
        results = await verifier.run(task["resolved_verification_commands"])
        gui_result = None
        gui = task.get("resolved_gui_verification")
        if gui and all(row["ok"] for row in results):
            async def notify(kind, data):
                await ws.send_json(envelope(kind, data, thread_id=thread_id, turn_id=owner))

            gui_result = await run_gui(gui, execute, view.tools, owner, notify=notify)
            results.append(gui_result)
            if gui_result["ok"] and (gui.get("vision_profile_id") or task["config"].get("vision_profile_id")):
                results.append({"command": "vision observation", "ok": False, "category": "configuration",
                                "summary": "截图保留于本机，OpenCode 任务尚未接通所配置的视觉观察模型"})
            for evidence in gui_result.get("evidence", []):
                for field in ("stdout", "stderr", "summary"):
                    if field in evidence:
                        evidence[field] = redact_text(evidence[field], exact_secrets=service.server._exact_secrets(), max_chars=5000)
        for row in results:
            for field in ("summary", "stdout", "stderr"):
                if field in row:
                    row[field] = redact_text(row[field], exact_secrets=service.server._exact_secrets(), max_chars=5000)
        snapshot = await service.workspace_fingerprint(view)
        diff = await view.tools.execute("git_diff", {})
        passed = bool(results) and all(row["ok"] for row in results) and diff.ok and before == snapshot
        report = {"passed": passed, "tests": results, "diff": redact_text(diff.stdout, exact_secrets=service.server._exact_secrets()),
                  "workspace_fingerprint": snapshot, "gui_verification": ("PASS" if gui_result["ok"] else "FAIL") if gui_result else "NOT RUN",
                  "review": "独立验收通过，等待审阅 Diff" if passed else "独立验收未通过"}
        return runtime.transition(task_id, "awaiting_approval" if passed else "paused", report["review"],
                                  verification=results, report=report)
    except (ValueError, OSError, TimeoutError):
        runtime.transition(task_id, "paused", "独立验收无法完成")
        raise
    finally:
        if view:
            await view.tools.desktop.close_owner(owner)
            await view.tools.processes.close_owner(owner)
        service.server.approvals.finish_turn(owner)
