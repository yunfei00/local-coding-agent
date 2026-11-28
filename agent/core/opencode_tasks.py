"""Workspace and acceptance services for tasks executed by Electron's OpenCode runtime."""
from pathlib import Path

from agent.core.diagnostics import redact_text
from agent.core.verification import VerificationEngine, acceptance_changes, acceptance_snapshot, discover_commands
from agent.llm.base import ToolCall
from agent.server.protocol import new_id


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
        if task["config"].get("gui_verification") or (view.workspace.root / ".lca/gui-verification.json").exists():
            return runtime.transition(task_id, "paused", "OpenCode 任务的独立 GUI 验收尚未接通")
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
        for row in results:
            for field in ("summary", "stdout", "stderr"):
                if field in row:
                    row[field] = redact_text(row[field], exact_secrets=service.server._exact_secrets(), max_chars=5000)
        snapshot = await service.workspace_fingerprint(view)
        diff = await view.tools.execute("git_diff", {})
        passed = bool(results) and all(row["ok"] for row in results) and diff.ok and before == snapshot
        report = {"passed": passed, "tests": results, "diff": redact_text(diff.stdout, exact_secrets=service.server._exact_secrets()),
                  "workspace_fingerprint": snapshot, "gui_verification": "NOT RUN",
                  "review": "独立验收通过，等待审阅 Diff" if passed else "独立验收未通过"}
        return runtime.transition(task_id, "awaiting_approval" if passed else "paused", report["review"],
                                  verification=results, report=report)
    except (ValueError, OSError, TimeoutError):
        runtime.transition(task_id, "paused", "独立验收无法完成")
        raise
    finally:
        if view:
            await view.tools.processes.close_owner(owner)
        service.server.approvals.finish_turn(owner)
