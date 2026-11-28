from __future__ import annotations

import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
REPORT = ROOT / "validation-reports" / "p0-real-model-mcp.json"


def main() -> int:
    # Safe environment check - no secrets printed
    env_keys = ["OPENAI_API_KEY", "KIMI_API_KEY", "MOONSHOT_API_KEY", "DASHSCOPE_API_KEY", "QWEN_API_KEY", "ANTHROPIC_API_KEY"]
    present = [k for k in env_keys if os.environ.get(k)]
    report = {
        "ok": False,
        "status": "BLOCKED",
        "checks": [],
        "environment": {"model_env_keys_present": present, "count": len(present)},
        "reason": "",
    }
    if not present:
        report["reason"] = "No configured online model API key environment variables found in this execution environment. Real online model MCP call acceptance requires configured credentials; not faked."
        REPORT.parent.mkdir(parents=True, exist_ok=True)
        REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps({"ok": False, "status": "BLOCKED", "report": str(REPORT), "reason": report["reason"]}, ensure_ascii=False))
        return 2

    # Credentials present in env - do not print them. Minimal smoke would go here.
    # For safety, we only report that credentials exist and require explicit human-run live acceptance.
    report["status"] = "READY"
    report["reason"] = "Model credentials detected in environment. Run the full live acceptance through the desktop/agent flow with minimal quota; this script does not auto-consume quota."
    report["ok"] = True
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"ok": True, "status": "READY", "report": str(REPORT)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
