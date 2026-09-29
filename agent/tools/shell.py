from __future__ import annotations

import asyncio
import os
import shutil
import signal
import subprocess
import time
from contextlib import suppress
from typing import Any

from agent.tools.base import BaseTool, ToolError, ToolResult
from agent.tools.stream import ToolStreamState
from agent.tools.workspace import Workspace


MAX_OUTPUT_CHARS = 200_000
GRACEFUL_KILL_SECONDS = 1.5


def validate_command(command: str) -> None:
    if not command.strip():
        raise ToolError("EMPTY_COMMAND", "Command cannot be empty.")


def shell_command() -> tuple[str, list[str]]:
    if os.name == "nt":
        return "powershell.exe", ["-NoProfile", "-NonInteractive", "-Command"]

    pwsh = shutil.which("pwsh")
    if pwsh:
        return pwsh, ["-NoProfile", "-NonInteractive", "-Command"]

    return "/bin/bash", ["-lc"]


async def terminate_process_tree(
    process: asyncio.subprocess.Process,
) -> str:
    if process.returncode is not None:
        return "already_exited"

    if os.name == "nt":
        method = "taskkill"
        try:
            killer = await asyncio.create_subprocess_exec(
                "taskkill",
                "/PID",
                str(process.pid),
                "/T",
                "/F",
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            with suppress(asyncio.TimeoutError):
                await asyncio.wait_for(killer.wait(), timeout=5)
        except (FileNotFoundError, ProcessLookupError, PermissionError):
            method = "kill"
            with suppress(ProcessLookupError):
                process.kill()

        with suppress(asyncio.TimeoutError, ProcessLookupError):
            await asyncio.wait_for(process.wait(), timeout=3)
        return method

    try:
        group_id = os.getpgid(process.pid)
    except ProcessLookupError:
        return "already_exited"

    with suppress(ProcessLookupError):
        os.killpg(group_id, signal.SIGTERM)

    try:
        await asyncio.wait_for(process.wait(), timeout=GRACEFUL_KILL_SECONDS)
        return "sigterm"
    except asyncio.TimeoutError:
        pass

    with suppress(ProcessLookupError):
        os.killpg(group_id, signal.SIGKILL)
    with suppress(asyncio.TimeoutError, ProcessLookupError):
        await asyncio.wait_for(process.wait(), timeout=3)
    return "sigkill"


class RunCommandTool(BaseTool):
    name = "run_command"
    description = (
        "Run a development command and return live stdout/stderr, exit code and duration. "
        "Stopping the Turn terminates the command process tree. "
        "The permission policy may require explicit approval for destructive, "
        "publishing, system-level or out-of-workspace operations."
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
                "description": (
                    "Working directory. Use a workspace-relative path normally. "
                    "An absolute path outside the workspace requires Full Access and approval."
                ),
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

        cwd = self.workspace.resolve(
            str(arguments.get("cwd") or "."),
            must_exist=True,
        )
        if not cwd.is_dir():
            raise ToolError("NOT_DIRECTORY", "Command cwd must be a directory.")

        timeout = min(max(int(arguments.get("timeout_seconds") or 120), 1), 600)
        executable, prefix = shell_command()
        started = time.perf_counter()
        stream_state = ToolStreamState()

        spawn_kwargs: dict[str, Any] = {
            "cwd": str(cwd),
            "stdout": asyncio.subprocess.PIPE,
            "stderr": asyncio.subprocess.PIPE,
            "env": os.environ.copy(),
        }
        if os.name == "nt":
            spawn_kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
        else:
            spawn_kwargs["start_new_session"] = True

        process = await asyncio.create_subprocess_exec(
            executable,
            *prefix,
            command,
            **spawn_kwargs,
        )

        if on_output:
            await on_output(
                stream_state.meta(
                    "process_started",
                    pid=process.pid,
                    command=command,
                    cwd=self.workspace.display(cwd),
                    timeout_seconds=timeout,
                )
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
                    for event in stream_state.output(label, text):
                        await on_output(event)

        stdout_task = asyncio.create_task(
            consume(process.stdout, stdout_parts, "stdout")
        )
        stderr_task = asyncio.create_task(
            consume(process.stderr, stderr_parts, "stderr")
        )

        try:
            await asyncio.wait_for(process.wait(), timeout=timeout)
            await asyncio.gather(stdout_task, stderr_task)
        except asyncio.TimeoutError as exc:
            if on_output:
                await on_output(
                    stream_state.meta(
                        "process_terminating",
                        pid=process.pid,
                        reason="timeout",
                    )
                )
            method = await terminate_process_tree(process)
            await asyncio.gather(
                stdout_task,
                stderr_task,
                return_exceptions=True,
            )
            if on_output:
                await on_output(
                    stream_state.meta(
                        "process_terminated",
                        pid=process.pid,
                        reason="timeout",
                        method=method,
                        duration_ms=int((time.perf_counter() - started) * 1000),
                    )
                )
            raise ToolError(
                "COMMAND_TIMEOUT",
                f"Command exceeded timeout of {timeout} seconds and its process tree was terminated.",
            ) from exc
        except asyncio.CancelledError:
            if on_output:
                with suppress(Exception):
                    await on_output(
                        stream_state.meta(
                            "process_terminating",
                            pid=process.pid,
                            reason="user_cancelled",
                        )
                    )
            method = await terminate_process_tree(process)
            stdout_task.cancel()
            stderr_task.cancel()
            await asyncio.gather(
                stdout_task,
                stderr_task,
                return_exceptions=True,
            )
            if on_output:
                with suppress(Exception):
                    await on_output(
                        stream_state.meta(
                            "process_terminated",
                            pid=process.pid,
                            reason="user_cancelled",
                            method=method,
                            duration_ms=int((time.perf_counter() - started) * 1000),
                        )
                    )
            raise

        stdout = "".join(stdout_parts)
        stderr = "".join(stderr_parts)
        if len(stdout) > MAX_OUTPUT_CHARS:
            stdout = stdout[-MAX_OUTPUT_CHARS:]
        if len(stderr) > MAX_OUTPUT_CHARS:
            stderr = stderr[-MAX_OUTPUT_CHARS:]

        duration_ms = int((time.perf_counter() - started) * 1000)
        code = int(process.returncode or 0)

        if on_output:
            await on_output(
                stream_state.meta(
                    "process_exited",
                    pid=process.pid,
                    exit_code=code,
                    duration_ms=duration_ms,
                    **stream_state.snapshot(),
                )
            )

        return ToolResult(
            ok=code == 0,
            summary=f"Command exited with code {code} in {duration_ms} ms.",
            stdout=stdout,
            stderr=stderr,
            exit_code=code,
            duration_ms=duration_ms,
            data={
                "command": command,
                "cwd": self.workspace.display(cwd),
                "pid": process.pid,
                "stream": stream_state.snapshot(),
            },
        )
