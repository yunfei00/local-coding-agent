"""Independent validation through the existing authorized command tool."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import time
import uuid


def acceptance_snapshot(root: Path) -> dict:
    """Freeze existing test expectations/configuration, never store file bodies."""
    snapshot = {}
    def candidates():
        for directory, dirs, files in os.walk(root,followlinks=False):
            dirs[:] = [d for d in dirs if d not in {'.git','node_modules','.venv','__pycache__','dist','lib'}]
            for name in files:
                yield Path(directory)/name
    for path in candidates():
        relative = path.relative_to(root)
        if any(p in {'.git','node_modules','.venv','__pycache__','dist','lib'} for p in relative.parts) or not path.is_file():
            continue
        name = path.name
        is_test = any(p in ('tests','__tests__') for p in relative.parts) or name.startswith('test_') or '.test.' in name or '.spec.' in name
        config = str(relative).replace('\\','/') in ('.lca/verification.json','.lca/gui-verification.json') or name in ('tsconfig.json','vitest.config.ts','jest.config.js','pytest.ini')
        if name == 'package.json':
            if path.stat().st_size > 262144 or not path.resolve().is_relative_to(root.resolve()):
                raise ValueError('Acceptance manifest outside workspace or too large')
            scripts = json.loads(path.read_text(encoding='utf-8')).get('scripts',{})
            # Missing hooks are frozen too: adding prestart/pretest must not
            # silently replace the trusted execution path. Old snapshots keep
            # their original subset comparison for compatibility.
            snapshot[str(relative)] = {'scripts':{k:scripts.get(k) for k in ('test','typecheck','build','pretest','posttest','pretypecheck','posttypecheck','prebuild','postbuild','start','prestart','poststart')}}
        elif (is_test or config) and path.suffix not in ('.pyc','.pyo'):
            if not path.resolve().is_relative_to(root.resolve()) or path.stat().st_size > 2*1024*1024 or len(snapshot) >= 2000:
                raise ValueError('Acceptance baseline exceeds bounded safe discovery')
            snapshot[str(relative)] = {'sha256':hashlib.sha256(path.read_bytes()).hexdigest()}
    return snapshot


def acceptance_changes(root: Path, baseline: dict) -> list[str]:
    current = acceptance_snapshot(root)
    changed=[]
    for name, original in baseline.items():
        candidate=current.get(name)
        if 'scripts' in original:
            if candidate is None or any(candidate.get('scripts',{}).get(k) != v for k,v in original['scripts'].items()):
                changed.append(name)
        elif candidate != original:
            changed.append(name)
    return changed


def discover_commands(root: Path, configured: list[str]) -> list[str]:
    if configured:
        return list(configured)
    custom = root / ".lca" / "verification.json"
    if custom.exists():
        if not custom.resolve().is_relative_to(root.resolve()) or custom.stat().st_size > 32768:
            raise ValueError("Verification configuration outside workspace or too large")
        values = json.loads(custom.read_text(encoding="utf-8"))
        commands = values.get("commands") if isinstance(values, dict) else None
        if not isinstance(commands, list) or not 1 <= len(commands) <= 12 or any(not isinstance(c, str) or not c.strip() or len(c) > 2000 for c in commands):
            raise ValueError(".lca/verification.json requires 1..12 commands")
        return commands
    commands = []
    package = root / "package.json"
    def confined(path: Path) -> bool:
        return path.resolve().is_relative_to(root.resolve())
    for path in (package, root / "pyproject.toml", root / "tests"):
        if path.exists() and not confined(path):
            raise ValueError("Verification discovery cannot read a path outside the workspace")
    if package.is_file() and package.stat().st_size < 100000:
        scripts = json.loads(package.read_text(encoding="utf-8")).get("scripts", {})
        for name in ("test", "typecheck", "build"):
            if name in scripts:
                commands.append("npm run " + name)
    if (root / "tests").is_dir() and any((root / "tests").glob("test*.py")):
        pyproject = root / "pyproject.toml"
        has_uv = pyproject.exists()
        if has_uv and pyproject.stat().st_size > 262144:
            raise ValueError("pyproject.toml exceeds bounded verification discovery size")
        pytest = has_uv and "pytest" in pyproject.read_text(encoding="utf-8")
        commands.append("uv run pytest" if pytest else ("uv run " if has_uv else "") + "python -m unittest discover -s tests -v")
    if commands and (root / ".git").exists():
        commands.append("git diff --check")
    return commands


def classify(result: dict) -> str:
    if result.get("ok") and result.get("exit_code") == 0:
        return "passed"
    code = str((result.get("error") or {}).get("code", ""))
    text = (str(result.get("stdout", "")) + "\n" + str(result.get("stderr", "")) + "\n" + str(result.get("summary", ""))).lower()
    if "PERMISSION" in code or "APPROVAL" in code or "access is denied" in text:
        return "permission"
    if "TIMEOUT" in code:
        return "timeout"
    if code == "COMMAND_OUTPUT_FAILED":
        return "environment"  # Output transport failure is not evidence of broken code.
    if any(t in text for t in ("modulenotfounderror", "no module named", "commandnotfound", "not recognized", "enoent", "cannot find module")):
        return "environment"
    if any(t in text for t in ("econnrefused", "enotfound", "network is unreachable", "connectionerror", "unable to resolve")):
        return "network"
    if any(t in text for t in ("no tests ran", "collected 0 items", "ran 0 tests", "missing script", "unrecognized arguments", "usageerror")):
        return "configuration"
    if any(t in text for t in ("assertionerror", "assert ", "failed (failures", "failed:", "test failed")):
        return "assertion"
    return "code"


def failure_fingerprint(results: list[dict], diff: str) -> str:
    # Ignore durations/PIDs/temp roots so recurring failures compare reliably.
    def normalized(text: str) -> str:
        text = re.sub(r"\b\d+(?:\.\d+)?(?=\s*(?:ms|s|seconds?)\b)", "#", text)
        return re.sub(r"\b\d+(?:\.\d+)?\b", "#", text)
    failures = [{"command": r["command"], "category": r["category"], "exit_code": r.get("exit_code"),
                 "summary": normalized(r.get("summary", ""))} for r in results if not r.get("ok")]
    return hashlib.sha256((json.dumps(failures, sort_keys=True) + diff).encode()).hexdigest()


class VerificationEngine:
    def __init__(self, log_root: Path, execute, timeout: int):
        self.log_root, self.execute, self.timeout = log_root, execute, min(timeout, 600)

    async def run(self, commands: list[str]) -> list[dict]:
        if not commands:
            return [{"command": "", "ok": False, "category": "configuration", "exit_code": None,
                     "summary": "No verification command configured or discovered; task cannot pass.", "duration_ms": 0}]
        self.log_root.mkdir(parents=True, exist_ok=True)
        results = []
        for command in commands:
            log_path = self.log_root / (uuid.uuid4().hex + ".log")
            written, truncated = 0, False
            started = time.perf_counter()
            with log_path.open("w", encoding="utf-8") as log:
                async def raw_output(stream, text):
                    nonlocal written, truncated
                    # Memory is bounded by the shell; retain full logs up to 64 MiB.
                    data = f"[{stream}] {text}"
                    if written + len(data.encode("utf-8")) <= 64 * 1024 * 1024:
                        log.write(data)
                        written += len(data.encode("utf-8"))
                    else:
                        truncated = True
                result = await self.execute("run_command", {"command": command, "timeout_seconds": self.timeout}, on_raw_output=raw_output,
                    environment={"PYTHONPYCACHEPREFIX": str(self.log_root / "python-cache" / uuid.uuid4().hex), "PYTHONDONTWRITEBYTECODE": "1"})
            category = classify(result)
            # An empty unittest/pytest run is never independent acceptance evidence.
            output = str(result.get("stdout", "")) + "\n" + str(result.get("stderr", ""))
            if re.search(r"Ran 0 tests|no tests ran|collected 0 items", output, re.I):
                category = "configuration"
            if truncated:
                category = "configuration"
            if (result.get("data") or {}).get("log_truncated"):
                category = "configuration"
            results.append({"command": command, "ok": category == "passed", "category": category,
                            "exit_code": result.get("exit_code"), "duration_ms": round((time.perf_counter() - started) * 1000),
                            "stdout": str(result.get("stdout", ""))[-4000:], "stderr": str(result.get("stderr", ""))[-4000:],
                            "summary": (output.strip() or str(result.get("summary", "")))[-5000:],
                            "log_path": str(log_path), "log_truncated": truncated,
                            "execution": {k:v for k,v in (result.get("data") or {}).items() if k in {"process_id", "pid", "shell", "state", "log_path", "metadata_path"}},
                            "error_code": (result.get("error") or {}).get("code")})
        return results
