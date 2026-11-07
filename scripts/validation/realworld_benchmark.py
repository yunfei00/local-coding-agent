"""Phase 0 serial runner using the existing production WebSocket driver."""
import argparse
import asyncio
from collections import Counter
from contextlib import closing, contextmanager
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import urllib.parse

import aiohttp

from agent.core.runtime_events import failure_class
from scripts.validation.local_ollama_benchmark import attempt, discover
from scripts.validation.realworld_cases import verify_command_evidence
from scripts.validation.realworld_extended import CASES

MODEL = "gemma4:31b"
CATEGORIES = tuple(dict.fromkeys(case.category for case in CASES.values()))


def atomic(path, data):
    pending = path.with_suffix(path.suffix + ".tmp")
    pending.write_text(data, encoding="utf-8")
    os.replace(pending, path)


def save_json(path, data):
    atomic(path, json.dumps(data, indent=2, ensure_ascii=False) + "\n")


def signature():
    root = Path(__file__).parent
    paths = ["realworld_benchmark.py", "realworld_cases.py", "realworld_extended.py", "local_ollama_benchmark.py"]
    return hashlib.sha256(b"".join((root / name).read_bytes() for name in paths)).hexdigest()


@contextmanager
def run_lock(directory):
    with (directory / ".run.lock").open("a+b") as handle:
        try:
            if os.name == "nt":
                import msvcrt
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as error:
            raise SystemExit("Another runner is using this output directory.") from error
        yield


def collect(root, *, write_events=True):
    db = root / "data" / "local-coding-agent.sqlite3"
    events = []
    recoveries = []
    if db.is_file():
        with closing(sqlite3.connect(db.as_uri() + "?mode=ro", uri=True)) as connection:
            rows = connection.execute("SELECT kind, metadata_json FROM runtime_events ORDER BY sequence")
            for kind, data in rows:
                data = json.loads(data)
                public = {k: data[k] for k in ("input_tokens", "output_tokens", "estimated", "duration_ms",
                    "error_code", "http_status", "finish_reason", "recovery_count", "status") if k in data}
                events.append({"event": kind, **public})
            if connection.execute("SELECT 1 FROM sqlite_master WHERE name='agent_execution_runs'").fetchone():
                recoveries = [json.loads(row[0]) for row in connection.execute("SELECT data_json FROM agent_execution_runs")]
    if write_events:
        save_json(root / "model-events.json", events)
    usage = [e for e in events if e["event"] == "response.completed"
             and all(type(e.get(k)) is int and e[k] >= 0 for k in ("input_tokens", "output_tokens"))]
    count = sum(e["event"] == "request.dispatched" for e in events)
    errors = Counter(failure_class(e["error_code"]) for e in events if e.get("error_code"))
    return {"tokens": {"input": sum(e["input_tokens"] for e in usage),
                       "output": sum(e["output_tokens"] for e in usage),
                       "reported_calls": len(usage)} if usage else None,
            "model_calls": count, "model_error_classes": dict(errors),
            "recovery_count": sum(row.get("recovery_count", 0) for row in recoveries),
            "completion_repair_count": sum(row.get("completion_recovery_attempts", 0) for row in recoveries)}


def render(out, manifest, results, prior):
    counts = Counter(r["status"] for r in results)
    prior_status = {(r["case"], r["repeat"]): r["status"] for r in (prior or {}).get("results", [])}
    lines = ["# Phase 0 真实工程基准", "", "模型 " + MODEL,
             "源码 " + manifest["commit"], "",
             " | ".join(f"{state} {counts[state]}" for state in ("PASS", "FAIL", "BLOCKED", "NOT_RUN")), "",
             "| 用例 | 轮次 | 状态 | 失败分类 | 秒 | 模型/工具 | 历史状态 |",
             "|---|---:|---|---|---:|---|---|"]
    for r in results:
        lines.append(f"| {r['case']} {CASES[r['case']].title} | {r['repeat']} | {r['status']} | "
                     f"{r.get('failure') or '—'} | {r.get('seconds', '—')} | "
                     f"{r.get('model_calls', '—')}/{r.get('tool_calls', '—')} | "
                     f"{prior_status.get((r['case'], r['repeat']), '—')} |")
    save_json(out / "results.json", {"manifest": manifest, "counts": dict(counts), "results": results})
    atomic(out / "report.md", "\n".join(lines) + "\n")


async def run(args):
    out = args.output.resolve()
    prior = json.loads(args.compare.read_text(encoding="utf-8")) if args.compare else None
    config = {"context_window": args.context, "max_output_tokens": None, "model_steps": args.steps,
              "request_seconds": args.request_seconds, "case_seconds": args.case_seconds}
    commit = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    selected = [(id, repeat) for id, case in CASES.items() if (not args.case or id in args.case)
                and (not args.category or case.category in args.category) for repeat in range(1, args.repeat+1)]
    if args.retry:
        previous = json.loads(args.retry.read_text(encoding="utf-8"))["results"]
        allowed_ids = {id for id, _ in selected}
        selected = sorted({(r["case"], r["repeat"]) for r in previous
                           if r["status"] in {"FAIL", "BLOCKED"} and r["case"] in allowed_ids})
    manifest = {"commit": commit, "driver": signature(), "model": MODEL, "config": config,
                "planned": [list(pair) for pair in selected]}
    if args.resume:
        saved = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
        if saved != manifest:
            raise SystemExit("Resume requires the same source, driver, selection and budget.")
    else:
        out.mkdir(parents=True, exist_ok=False)
        save_json(out / "manifest.json", manifest)
    with run_lock(out):
        await execute(args, out, selected, manifest, prior, config)


async def execute(args, out, selected, manifest, prior, config):
    scratch = Path(tempfile.mkdtemp(prefix="lca-phase0-")).resolve()
    base = {}
    url = None
    if args.ollama_url:
        candidate = urllib.parse.urlsplit(args.ollama_url)
        if candidate.scheme not in {"http","https"} or not candidate.hostname or any(
                (candidate.username,candidate.password,candidate.query,candidate.fragment)):
            raise SystemExit("Use an HTTP(S) Ollama base URL without credentials.")
        url = args.ollama_url.rstrip("/")
    else:
        try:
            url, base, _ = discover(profiles=True).get(MODEL, (None, {}, {}))
        except (OSError, sqlite3.Error, KeyError, TypeError, ValueError):
            pass
    profile = {"model_id": MODEL, "display_name": MODEL, "context_window": args.context,
               "max_output_tokens": None, "temperature": base.get("temperature")}
    results = {}
    def publish():
        render(out, manifest, [results.get((id,n), {"case":id, "repeat":n, "status":"NOT_RUN"})
                               for id,n in selected], prior)
    for id, n in selected:
        shard = out / f"{id}-{n}.json"
        if shard.exists():
            results[id,n] = json.loads(shard.read_text(encoding="utf-8"))
    publish()
    async with aiohttp.ClientSession() as session:
        online = False
        if url:
            try:
                async with session.get(url + "/api/tags", timeout=8) as response:
                    online = response.ok and any(item["name"] == MODEL for item in (await response.json())["models"])
            except (aiohttp.ClientError, TimeoutError, ValueError, KeyError):
                pass
        for id, n in selected:
            if (id,n) in results:
                continue
            scenario = CASES[id]
            row = {"case": id, "repeat": n, "model": MODEL, "status": "BLOCKED"}
            dependency = "node" if scenario.language == "node" else "git" if scenario.git else None
            if not online:
                row["failure"] = "MODEL_UNAVAILABLE"
            elif dependency and not shutil.which(dependency):
                row["failure"] = "ENVIRONMENT_FAILURE"
            else:
                root = scratch / f"{id}-{n}"
                try:
                    row = await attempt(session, Path(sys.executable), url, MODEL, id, root, n,
                                        True, profile=profile, options=config, scenario=scenario)
                    row.update(collect(root))
                    if row.get("code") == "UNIFIED_READ_ONLY_INTENT":
                        row["failure"] = "AGENT_INTENT_CLASSIFICATION"
                    elif row.get("code") == "PLAN_RESUME_CONFIRMATION_REQUIRED":
                        row.update(status="BLOCKED", failure="PRODUCT_RESUME_CONFIRMATION")
                    elif row.get("failure") == "TOOL_PERMISSION" and row.get("harness_denials"):
                        row.update(status="BLOCKED", failure="HARNESS_APPROVAL_DENIED")
                except (OSError, sqlite3.Error, ValueError, AssertionError, subprocess.SubprocessError) as error:
                    row.update(status="BLOCKED", failure="HARNESS_FAILURE", detail=type(error).__name__)
                row["evidence"] = str(root)
            save_json(out / f"{id}-{n}.json", row)
            results[id,n] = row
            publish()
            print(id, n, row["status"], row.get("failure"), flush=True)


def derive(row):
    """Use already retained evidence; do not execute the prior worktree again."""
    if not row.get("evidence"):
        return
    root = Path(row["evidence"])
    if not root.is_dir():
        row["evidence_status"] = "MISSING_SCRATCH"
        return
    row.update(collect(root, write_events=False))
    row["raw_status"] = row["status"]
    if row.get("code") == "UNIFIED_READ_ONLY_INTENT":
        row["failure"] = "AGENT_INTENT_CLASSIFICATION"
    if row.get("code") == "PLAN_RESUME_CONFIRMATION_REQUIRED":
        row.update(status="BLOCKED", failure="PRODUCT_RESUME_CONFIRMATION")
    if row["status"] != "PASS" or row["case"] not in {"10", "22", "25", "29"}:
        return
    commands = {}
    tools = []
    with (root / "turn-events.jsonl").open(encoding="utf-8") as trace:
        for line in trace:
            event = json.loads(line)
            if event["type"] not in {"tool.started", "tool.completed"}:
                continue
            payload = json.loads(event["payload"])
            id = payload.get("tool_call_id")
            if event["type"] == "tool.started":
                commands[id] = payload.get("arguments", {}).get("command")
            else:
                result = payload.get("result", {})
                tools.append({"verification_command":commands.pop(id, None),
                              "exit_code":result.get("exit_code", (result.get("data") or {}).get("exit_code"))})
    try:
        verify_command_evidence(row["case"], tools)
    except AssertionError as error:
        row.update(status="FAIL", failure="DELIVERY_ASSERTION", assertion_failure=str(error))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--case", choices=CASES, action="append")
    parser.add_argument("--category", choices=CATEGORIES, action="append")
    parser.add_argument("--repeat", type=int, choices=(1,2,3), default=1)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--retry", type=Path)
    parser.add_argument("--compare", type=Path)
    parser.add_argument("--ollama-url")
    parser.add_argument("--context", type=int, choices=(8192,16384,32768), default=32768)
    parser.add_argument("--steps", type=int, choices=range(8,101), default=50)
    parser.add_argument("--request-seconds", type=int, choices=range(20,181), default=120)
    parser.add_argument("--case-seconds", type=int, choices=range(60,601), default=300)
    parser.add_argument("--rebuild-report", type=Path, help="Re-derive a report from prior evidence into a new directory")
    args = parser.parse_args()
    if args.rebuild_report:
        previous = json.loads(args.rebuild_report.read_text(encoding="utf-8"))
        args.output.mkdir(parents=True, exist_ok=False)
        for row in previous["results"]:
            derive(row)
        render(args.output, {**previous["manifest"], "derived_driver":signature()}, previous["results"], None)
    else:
        asyncio.run(run(args))


if __name__ == "__main__":
    main()
