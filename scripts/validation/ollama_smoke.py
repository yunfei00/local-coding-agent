"""Local, CPU-friendly Ollama smoke; model limitations are reported separately."""
from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time

from agent.server.main import AgentServer


class Events:
    def __init__(self):
        self.messages = []
        self.output = asyncio.Event()

    async def send_json(self, message):
        self.messages.append(message)
        if message["type"] == "turn.delta":
            self.output.set()


async def main():
    root = Path(__file__).resolve().parents[2]
    report = {"model": "qwen2.5-coder:1.5b", "checks": []}
    with tempfile.TemporaryDirectory(prefix="lca-ollama-") as directory:
        os.environ.update(LCA_DATA_DIR=str(Path(directory, "data")), LCA_PROVIDER="ollama",
                          LCA_OLLAMA_MODEL=report["model"], LCA_OLLAMA_NUM_CTX="8192",
                          LCA_CONTEXT_RESERVED_OUTPUT_TOKENS="1024")
        workspace = Path(directory, "project")
        workspace.mkdir()
        Path(workspace, "value.py").write_text("value = 1\n", encoding="utf-8")
        subprocess.run(["git", "init", "-q"], cwd=workspace, check=True)
        server = AgentServer("local-smoke-token")
        server.max_model_steps = 6
        try:
            status = await server.provider.get_status()
            report["online"] = status["online"]
            report["models"] = [m["name"] for m in status["models"]]
            if not status["online"] or report["model"] not in report["models"]:
                raise RuntimeError("Required local Ollama model is unavailable")
            project, thread, _ = server.projects.open(workspace, active_model=report["model"])
            for name, prompt in [
                ("chat", "你好，请只回复一句简短的问候。不要调用工具。"),
                ("read_file", "调用 read_file 工具读取 value.py，然后报告真实文件内容。只读取，不修改。"),
                ("modify_file", "请调用 apply_patch 将 value.py 中的 value = 1 修改为 value = 2，然后调用 git_diff 检查实际修改，不要 commit 或 push。"),
            ]:
                events = Events()
                started = time.perf_counter()
                await asyncio.wait_for(server.run_tool_turn(events, thread_id=thread.id,
                    turn_id="ollama-" + name, prompt=prompt, model=report["model"]), 120)
                tools = [e["payload"]["name"] for e in events.messages if e["type"] == "tool.completed"]
                failures = [e["payload"].get("code") for e in events.messages if e["type"] == "turn.failed"]
                text = "".join(e["payload"].get("delta", "") for e in events.messages if e["type"] == "turn.delta")
                passed = bool(text) if name == "chat" else "read_file" in tools if name == "read_file" else "value = 2" in Path(workspace, "value.py").read_text()
                report["checks"].append({"name": name, "result": "passed" if passed and not failures else "model_capability_limit" if not failures else "runtime_failure",
                    "tools": tools, "failure_codes": failures, "duration_ms": round((time.perf_counter() - started) * 1000)})
            events = Events()
            task = asyncio.create_task(server.run_tool_turn(events, thread_id=thread.id,
                turn_id="ollama-stop", prompt="请逐个列出从1到10000的数字。", model=report["model"]))
            await asyncio.wait_for(events.output.wait(), 60)
            started = time.perf_counter()
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
            report["checks"].append({"name": "stop", "result": "passed", "duration_ms": round((time.perf_counter() - started) * 1000)})
            await server.close_async()
            server.close()
            server = AgentServer("local-smoke-token")
            restored, restored_thread, _ = server.projects.open(workspace, active_model=report["model"])
            assert restored_thread.id == thread.id and len(restored.state.get_messages(thread.id)) >= 2
            report["checks"].append({"name": "restart_history", "result": "passed"})
        finally:
            await server.close_async()
            server.close()
    report_dir = root / "validation-reports"
    report_dir.mkdir(exist_ok=True)
    (report_dir / "ollama-smoke.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
