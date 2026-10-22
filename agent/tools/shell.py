from __future__ import annotations

import asyncio

from agent.tools.base import BaseTool, ToolError
from agent.tools.processes import ProcessManager, MAX_OUTPUT_CHARS, shell_command, terminate_process_tree


def validate_command(command: str) -> None:
    if not command.strip():
        raise ToolError("EMPTY_COMMAND", "Command cannot be empty.")


class RunCommandTool(BaseTool):
    name = "run_command"
    description = (
        "Run a foreground development command with live stdout/stderr, actual exit code and retained logs. "
        "shell=auto uses PowerShell on Windows and Bash elsewhere; cmd is also supported on Windows. "
        "For a development server use start_process, read_process and stop_process. "
        "Timeout/cancellation cleans up the owned process tree. Existing permissions and approvals apply."
    )
    parameters = {"type": "object", "properties": {
        "command": {"type": "string", "description": "Command text in the selected shell."},
        "cwd": {"type": "string", "description": "Workspace-relative working directory; external paths require approval."},
        "shell": {"type": "string", "enum": ["auto", "powershell", "cmd", "bash"], "default": "auto"},
        "timeout_seconds": {"type": "integer", "minimum": 1, "maximum": 86400, "default": 120},
    }, "required": ["command"]}

    def __init__(self, workspace, manager=None):
        self.manager = manager or ProcessManager(workspace)

    async def execute(self, arguments, *, on_output=None, on_raw_output=None, environment=None, owner_id=""):
        validate_command(str(arguments.get("command", "")))
        return await self.manager.run(arguments, owner=owner_id, on_output=on_output,
                                      on_raw_output=on_raw_output, environment=environment)


class StartProcessTool(RunCommandTool):
    name = "start_process"
    description = (
        "Start a long-running development server in an owned process tree and return an opaque process_id. "
        "Read readiness/output using read_process; starting alone does not prove readiness. "
        "Use stop_process when finished. Processes are stopped when the current Agent turn ends, "
        "fails or is cancelled, and at timeout_seconds (default 120, maximum 86400). "
        "This is not an untracked detached process. Permissions match run_command."
    )

    async def execute(self, arguments, *, on_output=None, owner_id=""):
        session = await self.manager.launch(arguments, owner=owner_id, on_output=on_output)
        await asyncio.sleep(0)
        return session.result()


class ReadProcessTool(BaseTool):
    name = "read_process"
    description = (
        "Read state, exit code and stdout/stderr of a process owned by this Agent turn. "
        "Use next_cursor from the previous result as cursor for new chunks. wait_seconds waits for new output "
        "or exit (maximum 10). Old output can be truncated; bounded full logs are retained separately."
    )
    parameters = {"type": "object", "properties": {
        "process_id": {"type": "string"}, "cursor": {"type": "integer", "minimum": 0},
        "wait_seconds": {"type": "number", "minimum": 0, "maximum": 10},
    }, "required": ["process_id"]}

    def __init__(self, manager):
        self.manager = manager

    async def execute(self, arguments, *, on_output=None, owner_id=""):
        session = self.manager.get(arguments.get("process_id"), owner_id)
        cursor, wait = arguments.get("cursor", 0), arguments.get("wait_seconds", 1)
        if isinstance(cursor, bool) or not isinstance(cursor, int) or cursor < 0:
            raise ToolError("INVALID_CURSOR", "cursor must be a nonnegative integer")
        if isinstance(wait, bool) or not isinstance(wait, (int, float)) or not 0 <= wait <= 10:
            raise ToolError("INVALID_PROCESS_WAIT", "wait_seconds must be 0..10")
        deadline = asyncio.get_running_loop().time() + wait
        while not session.task.done() and session.cursor <= cursor and asyncio.get_running_loop().time() < deadline:
            await asyncio.sleep(.05)
        return session.result(cursor=cursor)


class StopProcessTool(ReadProcessTool):
    name = "stop_process"
    description = "Stop a process owned by this Agent turn, clean up descendants and return final output. Never accepts arbitrary PIDs."
    parameters = {"type": "object", "properties": {"process_id": {"type": "string"}}, "required": ["process_id"]}

    async def execute(self, arguments, *, on_output=None, owner_id=""):
        return await self.manager.stop(arguments.get("process_id"), owner=owner_id)
