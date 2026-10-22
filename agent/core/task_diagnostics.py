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
    "cached_tokens", "actual_cost", "initial_reserved_tokens", "released_tokens", "settlement"}


def export_diagnostics(runtime, task_id, directory: Path, secrets=()):
    task = runtime.get(task_id)
    calls = []
    for call in runtime.calls(task_id, all_calls=True):
        calls.append({"task_id":task_id, "call_id":call["id"], "role":call["role"], "route":call["route"],
            "model":call["model"], "status":call["status"], "reserved_tokens":call["reserved_tokens"],
            "reserved_cost":call["reserved_cost"], "metadata":{k:v for k,v in call["usage"].items() if k in CALL_FIELDS}})
    error = task.get("last_error", {}).get("code")
    blocker = (error or (task.get("planning_failures") or [{}])[-1].get("code") or "PLANNING_IN_PROGRESS") if not task["planned"] else None
    report = {"schema_version":1, "task_id":task_id, "status":task["status"], "planned":task["planned"],
        "why_not_executing":blocker, "last_error_code":error,
        "last_error":{k:v for k,v in task.get("last_error", {}).items() if k in {"code","role","phase","exception_type"}},
        "planning_attempts":task.get("planning_attempts", 0), "planning_limit":task["config"]["budget"].get("planning_attempts", 4),
        "strategy":task["config"]["strategy"], "usage":runtime.usage(task_id),
        "calls":calls, "transitions":task.get("transitions", []),
        "privacy":"No prompts, response bodies, user files, headers, credentials, goals or Diffs are included."}
    # Redact credential values even if a configured model/display name contains one.
    def clean(value):
        if isinstance(value, str):
            return redact_text(value, exact_secrets=secrets, max_chars=100000)
        if isinstance(value, list): return [clean(v) for v in value]
        if isinstance(value, dict): return {k:clean(v) for k,v in value.items()}
        return value
    report = clean(report)
    text = json.dumps(report, ensure_ascii=False, indent=2)
    lines = ["# Task diagnostics", "", f"Task: {task_id}", f"Status: {task['status']}",
        f"Planning attempts: {report['planning_attempts']} / {report['planning_limit']}",
        f"Why Planning did not enter Executing: {blocker or 'Plan accepted; see transitions'}", "",
        "| Call | Stage / Role | Provider / Model | HTTP | Finish | Parse / Schema | Result / Next |",
        "| --- | --- | --- | --- | --- | --- | --- |"]
    for c in report["calls"]:
        m = c["metadata"]
        cell = lambda v: str(v).replace("|", "/").replace("\n", " ").replace("\r", " ")
        lines.append("| " + " | ".join(map(cell, [c["call_id"], f"{m.get('phase')} / {c['role']}",
            f"{m.get('provider_type')} / {c['model']}", m.get("http_status"), m.get("finish_reason"),
            f"{m.get('parse_success')} / {m.get('schema_valid')}", f"{m.get('error_code', c['status'])} / {m.get('next_state')}"])) + " |")
    lines += ["", "Full allowlisted metadata and Usage:", "```json", text, "```", ""]
    markdown = "\n".join(lines)
    directory.mkdir(parents=True, exist_ok=True)
    paths = {}
    for suffix, content in (("json",text), ("md",markdown)):
        target = directory / (task_id + "." + suffix)
        temporary = target.with_suffix(target.suffix + ".tmp")
        temporary.write_text(content, encoding="utf-8")
        temporary.replace(target)
        paths[suffix] = str(target)
    return {"diagnostics":{"json":report, "markdown":markdown}, "paths":paths}
