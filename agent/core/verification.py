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


def preserve_acceptance_requested(goal: str) -> bool:
    text=re.sub(r'不(?:需要|用|必|要)保留原测试','',goal)
    return bool(re.search(r'(?:保留|保持).{0,10}(?:原|现有|已有).{0,6}(?:测试|tests)|(?:不要|不得|禁止).{0,8}修改.{0,8}测试|原测试.{0,8}不变|(?:preserve|keep).{0,30}(?:original|existing).{0,10}tests',text,re.I))


def protected_edit(root: Path, baseline: dict, tool: str, arguments: dict) -> str | None:
    """Block declared frozen expectations before mutation; never restore HEAD
    over a user's uncommitted test. Other dependencies in package.json may change.
    """
    if tool not in {'write_file','apply_patch','delete_file'}:return None
    path=(root/str(arguments.get('path',''))).resolve()
    if not path.is_relative_to(root.resolve()):return None
    def key(value):
        value=str(value).replace('\\','/')
        return value.casefold() if os.name=='nt' else value
    original={key(name):value for name,value in baseline.items()}.get(key(path.relative_to(root.resolve()).as_posix()))
    if original is None:return None
    if tool=='delete_file':return '已冻结的测试或验证配置禁止删除；原文件保留。'
    if 'sha256' in original:return '原测试或验证配置已冻结；未写入。请将新增测试放到新的测试文件，不覆盖原文件或削弱验收。'
    try:
        text=str(arguments.get('content','')) if tool=='write_file' else path.read_text(encoding='utf-8-sig')
        if tool=='apply_patch':
            old,new=arguments.get('old_text'),arguments.get('new_text')
            if not isinstance(old,str) or not isinstance(new,str) or not old or text.count(old)!=1 and not arguments.get('replace_all'):return None
            text=text.replace(old,new)
        scripts=json.loads(text).get('scripts',{})
        if any(scripts.get(key)!=value for key,value in original['scripts'].items()):return '既有验证脚本或执行钩子已冻结；未写入。可以添加其他依赖，不能替换测试命令以制造通过。'
    except (ValueError,TypeError,OSError,AttributeError):return '无法确认原验证脚本保持不变；未写入无效配置。'
    return None


def protected_workspace_files(root: Path, goal: str) -> dict[str, str]:
    """Fingerprint explicitly preserved existing files without storing their contents."""
    name = r'([A-Z][A-Z0-9_-]{1,63}|[\w./\\-]+\.[A-Za-z0-9]+)'
    paths = re.findall(r'(?:保持|保留)\s*[`"]?' + name + r'[`"]?\s*(?:原样|不变)', goal)
    paths += re.findall(r'(?:不要|不得|禁止)修改\s*[`"]?' + name + r'[`"]?', goal)
    result = {}
    for raw in paths[:20]:
        path = root / raw.replace('\\', '/')
        if (path.is_file() and path.resolve().is_relative_to(root.resolve())
                and path.stat().st_size <= 16 * 1024 * 1024):
            result[path.resolve().relative_to(root.resolve()).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
    return result


def protected_workspace_changes(root: Path, baseline: dict[str, str]) -> list[str]:
    changed = []
    for name, digest in baseline.items():
        path = root / name
        if (not path.is_file() or not path.resolve().is_relative_to(root.resolve())
                or path.stat().st_size > 16 * 1024 * 1024 or hashlib.sha256(path.read_bytes()).hexdigest() != digest):
            changed.append(name)
    return changed


def protected_workspace_tool(root: Path, baseline: dict[str, str], name: str, arguments: dict) -> str | None:
    if not baseline:
        return None
    if name in {'write_file', 'apply_patch', 'delete_file'}:
        path = (root / str(arguments.get('path', ''))).resolve()
        if any(path == (root / protected).resolve() for protected in baseline):
            return '用户要求保留该文件；没有执行写入或删除。'
    if name == 'start_process':
        return '当前任务有明确保留文件，不能在交付目录启动后台进程。请使用隔离验证。'
    if name == 'run_command':
        command = str(arguments.get('command', ''))
        if command.strip() in {'git diff --check', 'git status', 'git diff'} and arguments.get('cwd') in (None,'','.'):
            return None
        if arguments.get('isolated_cwd') is not True or 'lca_project_root' in command.lower():
            return '当前任务有明确保留文件。请用 isolated_cwd=true 在临时目录运行验证，不要引用原工程目录。'
    return None


def delivery_requirements(goal: str) -> dict:
    """Extract explicit, narrow requirements. Commands remain data for review."""
    readme = bool(re.search(r'(?:提供|新增|编写|创建|生成|include|write|add)\s*(?:中文\s*)?(?:a\s+)?README\b', goal, re.I))
    # Only recognize standalone, predictable test invocations. Never execute
    # arbitrary strings extracted from a natural-language instruction.
    commands = []
    for command in ('python -m unittest -q', 'npm test', 'npm run build'):
        if re.search(r'(?:执行(?:且最终通过)?(?:的)?|运行|run)\s*[`"]?' + re.escape(command) + r'(?=[`"。；，、（(]|\s*$)', goal, re.I):
            commands.append(command)
    return {'readme':readme, 'commands':commands}


def workflow_verification_contract(goal: str, intent: dict) -> dict:
    """Derive obligations from the user's goal, independently of the model DAG."""
    development = not intent['read_only'] and intent['kind'] in {'change', 'complex'}
    stateful = development and bool(re.search(r'持久化|跨进程|\bpersist\w*\b|\bstateful\b', goal, re.I))
    explicit_tests = bool(re.search(r'单元测试|功能测试|测试用例|\bunittest\b|\bpytest\b|\b(?:unit|functional|integration) tests?\b', goal, re.I))
    independent = development and (
        bool(re.search(r'独立(?:功能)?(?:测试|验证|验收)|independent (?:functional )?(?:tests?|verification|validation)', goal, re.I))
        or (explicit_tests and (stateful or intent['kind']=='complex'))
        or any(command != 'npm run build' for command in delivery_requirements(goal)['commands'])
    )
    return {'independent': independent, 'stateful': stateful}


def missing_deliverables(root: Path, requirements: dict, commands: list[dict]) -> list[str]:
    missing = []
    if requirements['readme']:
        names = ('README.md','README','README.rst','README.txt')
        if not any((root / name).is_file() and (root / name).resolve().is_relative_to(root.resolve())
                   and (root / name).stat().st_size > 0 for name in names):
            missing.append('README')
    succeeded = {row.get('command') for row in commands if row.get('exit_code') == 0}
    missing.extend(command for command in requirements['commands'] if command not in succeeded)
    return missing


def discover_commands(root: Path, configured: list[str]) -> list[str]:
    if configured:
        return list(configured)
    custom = root / ".lca" / "verification.json"
    if custom.exists():
        if not custom.resolve().is_relative_to(root.resolve()) or custom.stat().st_size > 32768:
            raise ValueError("Verification configuration outside workspace or too large")
        values = json.loads(custom.read_text(encoding="utf-8-sig"))
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
        manifest = json.loads(package.read_text(encoding="utf-8-sig"))
        scripts = manifest.get('scripts',{}) if isinstance(manifest,dict) else None
        if not isinstance(scripts,dict) or any(not isinstance(k,str) or not isinstance(v,str) for k,v in scripts.items()):
            raise ValueError('package.json scripts must be an object of command strings')
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
    elif any(path.is_file() and path.resolve().is_relative_to(root.resolve())
             and path.stat().st_size <= 262144
             and re.search(r'(?m)^\s*(?:import unittest\b|from unittest import\b)', path.read_text(encoding="utf-8-sig", errors="replace"))
             for path in root.glob("test_*.py")):
        # Root-level tests are also a standard unittest discovery layout.
        # Prefer pytest only when the manifest declares it.
        manifest = root / "pyproject.toml"
        if manifest.is_file() and manifest.stat().st_size > 262144:
            raise ValueError("pyproject.toml exceeds bounded verification discovery size")
        if manifest.is_file() and "pytest" in manifest.read_text(encoding="utf-8"):
            commands.append("uv run pytest")
        else:
            commands.append(("uv run " if manifest.is_file() else "") + "python -m unittest discover -v")
    if commands and (root / ".git").exists():
        commands.append("git diff --check")
    return commands


def classify(result: dict) -> str:
    code = str((result.get("error") or {}).get("code", ""))
    if 'CANCEL' in code:
        return 'cancelled'
    text = (str(result.get("stdout", "")) + "\n" + str(result.get("stderr", "")) + "\n" + str(result.get("summary", ""))).lower()
    if any(t in text for t in ("no tests ran", "collected 0 items", "ran 0 tests")):
        return "configuration"
    if result.get("ok") and result.get("exit_code") == 0:
        return "passed"
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
