from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agent.mcp.client import MCPClientManager, MCPServerConfig  # noqa: E402


def _report_path() -> Path:
    p = ROOT / "validation-reports" / "p0-mcp-real-acceptance.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--server", default=str(ROOT / "tests" / "mcp_test_server.py"))
    args = parser.parse_args()

    report: dict = {"ok": True, "checks": [], "blocked": [], "evidence": {}}
    root = Path(tempfile.mkdtemp(prefix="lca-mcp-accept-"))
    cfg = MCPServerConfig(
        name="lca-test",
        transport="stdio",
        command=sys.executable,
        args=[args.server, "--root", str(root)],
        timeout_seconds=30,
    )
    m = MCPClientManager([cfg])

    def check(name: str, ok: bool, detail: dict | str | None = None):
        report["checks"].append({"name": name, "ok": bool(ok), "detail": detail})
        if not ok:
            report["ok"] = False

    try:
        st = await m.connect("lca-test")
        check("connect", st.connected, {"server_name": st.server_name, "version": st.server_version})

        tools = await m.list_tools("lca-test")
        names = sorted(t.name for t in tools)
        check("discover", {"ping","echo","read_file","write_file","delete_file","long_running","get_call_history"}.issubset(names), {"tools": names})

        def sval(payload):
            v = payload.get("result", {}).get("value", {})
            if isinstance(v, dict) and isinstance(v.get("structured_content"), dict):
                return v["structured_content"]
            return v if isinstance(v, dict) else {}

        ping = await m.call_tool("lca-test", "ping", {})
        check("ping", not ping.get("is_error") and sval(ping).get("ok") is True, {"is_error": ping.get("is_error"), "value": sval(ping)})

        echo = await m.call_tool("lca-test", "echo", {"text": "hello", "extra": {"k": 1}})
        val = sval(echo)
        check("echo", val.get("text") == "hello" and (val.get("extra") or {}).get("k") == 1, {"value": val})

        w = await m.call_tool("lca-test", "write_file", {"path": "a.txt", "content": "HELLO"})
        check("write_file", (root / "a.txt").exists() and (root / "a.txt").read_text(encoding="utf-8") == "HELLO", {"file_exists": (root / "a.txt").exists(), "value": sval(w)})

        r = await m.call_tool("lca-test", "read_file", {"path": "a.txt"})
        check("read_file", sval(r).get("content") == "HELLO", {"value": sval(r)})

        d = await m.call_tool("lca-test", "delete_file", {"path": "a.txt"})
        check("delete_file", not (root / "a.txt").exists() and sval(d).get("existed") is True, {"value": sval(d)})

        # cancel long running
        task = asyncio.create_task(m.call_tool("lca-test", "long_running", {"seconds": 30, "tick_ms": 100}))
        await asyncio.sleep(0.5)
        task.cancel()
        cancelled = False
        try:
            await task
        except asyncio.CancelledError:
            cancelled = True
        except Exception as e:
            report["checks"].append({"name": "long_running_cancel", "ok": False, "detail": str(e)})
            report["ok"] = False
        else:
            report["checks"].append({"name": "long_running_cancel", "ok": False, "detail": "not cancelled"})
            report["ok"] = False
        if cancelled:
            check("long_running_cancel", True, {"cancelled": True})

        hist = await m.call_tool("lca-test", "get_call_history", {})
        hv = hist.get("result", {}).get("value", {})
        history = hv.get("structured_content", hv).get("history", []) if isinstance(hv, dict) else []
        check("call_history", isinstance(history, list) and len(history) >= 6, {"count": len(history) if isinstance(history, list) else None})

        await m.disconnect("lca-test")
        check("disconnect", True)

        st2 = await m.connect("lca-test")
        check("reconnect", st2.connected)

        report["evidence"]["test_root"] = str(root)
        report["evidence"]["history_tail"] = history[-5:] if isinstance(history, list) else []
    finally:
        await m.disconnect_all()

    out = _report_path()
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"ok": report["ok"], "checks": len(report["checks"]), "report": str(out)}, ensure_ascii=False))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
