"""Run local validation and print a compact, numbered failure report.

Usage: python scripts/validation/check.py
"""
from __future__ import annotations

import datetime as dt
import json
import os
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
REPORT_DIR = ROOT / "validation-reports"
COMMANDS = [
    ("PYTHON", [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-v"], ROOT),
    ("TYPECHECK", ["npm", "run", "typecheck"], ROOT / "desktop"),
    ("DESKTOP_TEST", ["npm", "run", "test"], ROOT / "desktop"),
    ("BUILD", ["npm", "run", "build"], ROOT / "desktop"),
]
ERROR_LINE = re.compile(r"^(?:ERROR|FAIL): (.+)|^(?:ModuleNotFoundError|ImportError|PermissionError|AssertionError|Error:|npm error|.*\berror TS\d+:).*$", re.I)


def extract_failures(output: str, stage: str, exit_code: int) -> list[dict[str, str]]:
    found: list[dict[str, str]] = []
    lines = output.splitlines()
    for i, line in enumerate(lines):
        match = ERROR_LINE.match(line.strip())
        if not match:
            continue
        detail = line.strip()
        if match.group(1):
            detail = match.group(1)
            for following in lines[i + 1:i + 24]:
                if following.strip().startswith(("ModuleNotFoundError:", "ImportError:", "PermissionError:", "AssertionError:")):
                    detail += " | " + following.strip()
                    break
        if detail not in [item["detail"] for item in found]:
            found.append({"stage": stage, "detail": detail[:450]})
    if exit_code and not found:
        found.append({"stage": stage, "detail": f"Process exited with code {exit_code}. See full log."})
    return found


def main() -> int:
    run_id = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    REPORT_DIR.mkdir(exist_ok=True)
    failures: list[dict[str, str]] = []
    log_parts: list[str] = []
    for stage, command, cwd in COMMANDS:
        print(f"[RUN] {stage}", flush=True)
        try:
            result = subprocess.run(command, cwd=cwd, capture_output=True, text=True, errors="replace", check=False)
            output = (result.stdout or "") + "\n" + (result.stderr or "")
            code = result.returncode
        except OSError as exc:
            output, code = str(exc), 1
        log_parts.append(f"===== {stage} (exit={code}) =====\n{output}")
        failures.extend(extract_failures(output, stage, code))
        print(f"[{'PASS' if code == 0 else 'FAIL'}] {stage}", flush=True)
    for i, item in enumerate(failures, 1):
        item["id"] = f"ERR-{i:03d}"
    log_path = REPORT_DIR / f"{run_id}.log"
    summary_path = REPORT_DIR / f"{run_id}.json"
    log_path.write_text("\n\n".join(log_parts), encoding="utf-8")
    summary_path.write_text(json.dumps({"run_id": run_id, "failures": failures}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n========== VALIDATION SUMMARY [{run_id}] ==========")
    print(f"Errors: {len(failures)}")
    for item in failures:
        print(f"[{item['id']}] {item['stage']}: {item['detail']}")
    print(f"Full log: {log_path}")
    print(f"Summary: {summary_path}")
    print("=" * 55)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
