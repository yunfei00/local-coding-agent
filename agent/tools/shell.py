from __future__ import annotations

import asyncio
import os
import re
import shutil
import time
from typing import Any

from agent.tools.base import BaseTool, ToolError, ToolResult
from agent.tools.workspace import Workspace


BLOCKED_PATTERNS = [
    r"(?i)\bremove-item\b",
    r"(?i)\bdel\b",
    r"(?i)\berase\b",
    r"(?i)\brmdir\b",
    r"(?i)\brd\s+/s\b",
    r"(?i)\brm\s+-",
    r"(?i)git\s+reset\s+--hard",
    r"(?i)git\s+clean\s+-",
    r"(?i)git\s+push\b",
    r"(?i)git\s+checkout\s+--\s+",
    r"(?i)\bformat\b",
    r"(?i)\bshutdown\b",
    r"(?i)\brestart-computer\b",
    r"(?i)\bstop-computer\b",
    r"(?i)\breg\s+(add|delete)\b",
]

MAX_OUTPUT_CHARS = 200_000


def validate_command(command: str) -> None:
    if not command.strip():
        raise ToolError("EMPTY_COMMAND", "Command cannot be empty.")
    for pattern in BLOCKED_PATTERNS:
        if re.search(pattern, command):
            raise ToolError(
                "COMMAND_BLOCKED",
                "This command is blocked during Phase 3. Destructive commands require the approval system introduced in Phase 5.",
            )


def shell_command() -> tuple[str, list[str]]:
    if os.name == "nt":
        return "powershell.exe", ["-NoProfile", "-NonInteractive", "-Command"]

    pwsh = shutil.which("pwsh")
    if pwsh:
        return pwsh, ["-NoProfile", "-NonInteractive", "-Command"]

    return "/bin/bash", ["-lc"]


class RunCommandTool(BaseTool):
    name = "run_command"
    description = (
        "Run a development command in the current workspace and return stdout, stderr and exit code. "
        "Use for tests, builds, package scripts and diagnostics. Destructive commands are blocked in Phase 3."
    )
    parameters = {
        "type": "object",
        "properties": {
            "command": {
                "type": "string",
                "description": "Command line to execute in the workspace shell.",
            },
            "cwd": {
                "type": "string",
                "description": "Optional workspace-relative working directory. Defaults to workspace root.",
            },
            "timeout_seconds": {
                "type": "integer",
                "minimum": 1,
                "maximum": 600,
                "description": "Timeout in seconds. Defaults to 120.",
            },
        },
        "required": ["command"],
    }

    def __init__(self, workspace: Workspace) -> None:
        self.workspace = workspace

    async def execute(self, arguments: dict[str, Any], *, on_output=None) -> ToolResult:
        command = str(arguments["command"])
        validate_command(command)

        cwd = self.workspace.resolve(str(arguments.get("cwd") or "."), must_exist=True)
        if not cwd.is_dir():
            raise ToolError("NOT_DIRECTORY", "Command cwd must be a directory.")

        timeout = min(max(int(arguments.get("timeout_seconds") or 120), 1), 600)
        executable, prefix = shell_command()
        started = time.perf_counter()

        process = await asyncio.create_subprocess_exec(
            executable,
            *prefix,
            command,
            cwd=str(cwd),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=os.environ.copy(),
        )

        stdout_parts: list[str] = []
        stderr_parts: list[str] = []

        async def consume(stream, target: list[str], label: str) -> None:
            while True:
                chunk = await stream.read(4096)
                if not chunk:
                    break
                text = chunk.decode("utf-8", errors="replace")
                target.append(text)
                if on_output:
                    await on_output(label + text)

        stdout_task = asyncio.create_task(consume(process.stdout, stdout_parts, "stdout:"))
        stderr_task = asyncio.create_task(consume(process.stderr, stderr_parts, "stderr:"))

        try:
            await asyncio.wait_for(process.wait(), timeout=timeout)
            await asyncio.gather(stdout_task, stderr_task)
        except asyncio.TimeoutError as exc:
            process.kill()
            await process.wait()
            await asyncio.gather(stdout_task, stderr_task, return_exceptions=True)
            raise ToolError(
                "COMMAND_TIMEOUT",
                f"Command exceeded timeout of {timeout} seconds.",
            ) from exc
        except asyncio.CancelledError:
            process.kill()
            with suppress_process_lookup():
                await process.wait()
            stdout_task.cancel()
            stderr_task.cancel()
            raise

        stdout = "".join(stdout_parts)
        stderr = "".join(stderr_parts)
        if len(stdout) > MAX_OUTPUT_CHARS:
            stdout = stdout[-MAX_OUTPUT_CHARS:]
        if len(stderr) > MAX_OUTPUT_CHARS:
            stderr = stderr[-MAX_OUTPUT_CHARS:]

        duration_ms = int((time.perf_counter() - started) * 1000)
        code = int(process.returncode or 0)

        return ToolResult(
            ok=code == 0,
            summary=f"Command exited with code {code} in {duration_ms} ms.",
            stdout=stdout,
            stderr=stderr,
            exit_code=code,
            duration_ms=duration_ms,
            data={
                "command": command,
                "cwd": self.workspace.relative(cwd),
            },
        )


class suppress_process_lookup:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return exc_type is ProcessLookupError
