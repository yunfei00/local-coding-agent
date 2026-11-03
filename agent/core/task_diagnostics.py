"""Allowlisted task diagnostics: no prompts, file bodies, headers or credentials."""
from __future__ import annotations

import json
from pathlib import Path
from agent.core.diagnostics import redact_text

CALL_FIELDS = {"task_id", "call_id", "sequence", "phase", "retry", "started_at", "ended_at",
    "provider", "provider_type", "connection_id", "model_profile_id", "http_status", "response_type",
    "finish_reason", "representation", "response_form", "response_chars", "response_fingerprint", "http_started_at", "http_ended_at",
    "parse_success", "schema_valid", "schema_errors", "error_code", "failure_reason", "next_state",
    "transition_at", "recovered_at", "request_sent", "request_dispatched", "estimated", "input_tokens", "output_tokens",
    "cached_tokens", "actual_cost", "initial_reserved_tokens", "released_tokens", "settlement",
    "requested_max_tokens", "response_complete", "tool_parse_success", "tool_json_error"}


def export_diagnostics(runtime, task_id, directory: Path, secrets=()):
    task = runtime.get(task_id)
    calls = []
    for call in runtime.calls(task_id, all_calls=True):
        calls.append({"task_id":task_id, "call_id":call["id"], "role":call["role"], "route":call["route"],
            "model":call["model"], "status":call["status"], "reserved_tokens":call["reserved_tokens"],
            "reserved_cost":call["reserved_cost"], "metadata":{k:v for k,v in call["usage"].items() if k in CALL_FIELDS}})
    error = task.get("last_error", {}).get("code")
    blocker = (error or (task.get("planning_failures") or [{}])[-1].get("code") or "PLANNING_IN_PROGRESS") if not task["planned"] else None
    # API accounting and model context are independent constraints. A local
    # request may fail its model window while API reservations remain zero.
    usage = runtime.usage(task_id)
    task_budget = task["config"]["budget"]
    budget_explanation = {
        "api_accounting": "API call/token limits apply only to route=api; local model calls do not reserve API tokens.",
        "model_context": "MODEL_CONTEXT_LIMIT is a per-request context-window check, not cumulative API token usage.",
        "api_reserved_tokens": usage.get("reserved_tokens", 0),
        "api_token_limit": task_budget.get("api_tokens"),
        "error_code": error,
        "error_budget_details": task.get("last_error", {}).get("budget") if error == "BUDGET_EXHAUSTED" else None,
    }
    report = {"schema_version":1, "task_id":task_id, "status":task["status"], "planned":task["planned"],
        "budget_explanation":budget_explanation,
        "why_not_executing":blocker, "last_error_code":error,
        "last_error":{k:v for k,v in task.get("last_error", {}).items() if k in {"code","role","phase","exception_type","budget"}},
        "config_source":task.get("config_source", "legacy-snapshot"), "config_snapshot_at":task.get("config_snapshot_at"),
        "task_limits":task["config"]["budget"], "global_limits":task.get("global_budget"),
        "global_usage":runtime.usage(),
        "planning_attempts":task.get("planning_attempts", 0), "planning_limit":task["config"]["budget"].get("planning_attempts", 4),
        "strategy":task["config"]["strategy"], "usage":runtime.usage(task_id),
        "calls":calls, "transitions":task.get("transitions", []), "executions":runtime.plans.executions(task_id),
        "privacy":"No prompts, response bodies, user files, headers, credentials, goals or Diffs are included."}
    current_issue = {
        "status":task["status"], "last_error":report["last_error"],
        "reason":str(task.get("reason",""))[:600],
        "unfinished_steps":[{"state":step["state"],"description":str(step.get("description",""))[:240]}
            for step in runtime.plans.get(task_id)["steps"]
            if step["state"] not in {"completed","skipped"}][:8],
        "recent_calls":calls[-8:], "recent_transitions":report["transitions"][-8:],
        "recent_executions":report["executions"][-8:],
        "usage":report["usage"], "budget_explanation":budget_explanation,
    }
    # Redact credential values even if a configured model/display name contains one.
    def clean(value):
        if isinstance(value, str):
            return redact_text(value, exact_secrets=secrets, max_chars=100000)
        if isinstance(value, list): return [clean(v) for v in value]
        if isinstance(value, dict): return {k:clean(v) for k,v in value.items()}
        return value
    report = clean(report)
    text = json.dumps(report, ensure_ascii=False, indent=2)
    markdown = "\n".join(["# Task diagnostics — current issue", "",
        "Task: " + task_id, "Status: " + str(task["status"]),
        "Last error: " + str(error or "none"),
        "Showing the current issue and last 8 events only; full history is saved in JSON.",
        "", "~~~json", json.dumps(clean(current_issue), ensure_ascii=False, indent=2),
        "~~~", ""])
    directory.mkdir(parents=True, exist_ok=True)
    paths = {}
    for suffix, content in (("json",text), ("md",markdown)):
        target = directory / (task_id + "." + suffix)
        temporary = target.with_suffix(target.suffix + ".tmp")
        temporary.write_text(content, encoding="utf-8")
        temporary.replace(target)
        paths[suffix] = str(target)
    return {"diagnostics":{"json":report, "markdown":markdown}, "paths":paths}
