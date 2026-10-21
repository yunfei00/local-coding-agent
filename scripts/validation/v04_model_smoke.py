"""Opt-in real-model fixture. API mode requires explicit paid-request consent."""
from __future__ import annotations

import argparse
import asyncio
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))


async def run(args) -> int:
    if args.mode == "api" and not args.allow_paid_api:
        raise SystemExit("Real API mode can incur charges. Explicit --allow-paid-api is required.")
    if args.mode == "api" and not os.getenv("LCA_OPENAI_BASE_URL"):
        raise SystemExit("Configure LCA_OPENAI_BASE_URL and LCA_OPENAI_API_KEY (if required); no credentials are guessed.")
    report_root = ROOT / "validation-reports" / ("v04-" + args.mode + "-" + datetime.now().strftime("%Y%m%d-%H%M%S"))
    report_root.mkdir(parents=True)
    os.environ["LCA_DATA_DIR"] = str(report_root / "data")
    from agent.server.main import AgentServer
    from agent.llm.router import validate_config
    server = AgentServer("fixture-only")
    async def approve(ws, **kwargs):
        if kwargs["tool_name"] != "git_worktree_create":
            return "deny"
        return "allow_once"  # Only isolated test fixture creation, never production approvals.
    server.approvals.request = approve
    class Events:
        async def send_json(self, event):
            if event["type"] in {"task.updated", "model.active", "model.compatibility"}:
                payload = event["payload"]
                print(payload.get("task", {}).get("status") or event["type"], flush=True)
    ws = Events()
    try:
        with tempfile.TemporaryDirectory(prefix="lca-v04-model-") as temp:
            repo = Path(temp) / "repo"
            shutil.copytree(ROOT / "manual-fixtures/v04-local-first", repo, ignore=shutil.ignore_patterns("__pycache__"))
            for command in (["init", "-q", "-b", "main"], ["config", "user.name", "Fixture"], ["config", "user.email", "fixture@example.test"], ["add", "."], ["commit", "-qm", "fixture"]):
                subprocess.run(["git", *command], cwd=repo, check=True, capture_output=True)
            project, thread, _ = server.projects.open(str(repo), active_model=args.model)
            route = "local" if args.mode == "ollama" else "api"
            config = validate_config({"strategy": "local-only" if route == "local" else "api-only",
                "roles": {r: {"model": args.model, "context_window": args.context, "output_limit": 1024,
                               "tool_mode": "json" if route == "local" else "native"} for r in ("planner", "executor", "reviewer", "escalation")},
                "budget": {"api_calls": 3, "api_tokens": 30000, "task_seconds": args.seconds, "request_seconds": min(args.seconds, 120), "local_repairs": 1},
                "verification_commands": ["uv run --no-project python -m unittest discover -s tests -v", "git diff --check"]})
            await server.tasks.handle(ws, {"type": "task.start", "thread_id": thread.id,
                "payload": {"goal": "Read calculator.py. Fix add(a,b) so it returns a+b instead of a-b. Use actual tools. Keep the tests unchanged. Inspect the Diff.", "config": config}}, set())
            await asyncio.gather(*list(server.active_turns.values()))
            task = server.store.task_runtime.list(thread.id)[0]
            result = server.tasks.public(task)
            result["real_provider"] = args.mode
            result["passed"] = task["status"] == "awaiting_approval" and all(r["ok"] for r in task["verification"])
            result["paid_requests_authorized"] = args.allow_paid_api
            (report_root / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
            print(json.dumps({"passed":result["passed"], "status":task["status"], "reason":task["reason"],
                              "usage":result["usage"], "report":str(report_root / "result.json")}, ensure_ascii=False), flush=True)
            return 0 if result["passed"] else 1
    finally:
        await server.close_async()
        server.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=["ollama", "api"], default="ollama")
    parser.add_argument("--model", required=True)
    parser.add_argument("--context", type=int, default=8192)
    parser.add_argument("--seconds", type=int, default=240)
    parser.add_argument("--allow-paid-api", action="store_true", help="Consent to real API charges")
    raise SystemExit(asyncio.run(run(parser.parse_args())))
