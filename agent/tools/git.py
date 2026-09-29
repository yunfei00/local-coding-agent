from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from agent.tools.base import BaseTool, ToolError, ToolResult
from agent.tools.diff import parse_unified_diff, synthesize_untracked_file
from agent.tools.workspace import DEFAULT_IGNORED_DIRS, Workspace


async def _git(
    workspace: Workspace,
    *args: str,
    timeout: int = 30,
) -> tuple[int, str, str]:
    try:
        process = await asyncio.create_subprocess_exec(
            "git",
            *args,
            cwd=str(workspace.root),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    except FileNotFoundError as exc:
        raise ToolError("GIT_NOT_FOUND", "git executable was not found.") from exc

    try:
        stdout_b, stderr_b = await asyncio.wait_for(
            process.communicate(),
            timeout=timeout,
        )
    except asyncio.TimeoutError as exc:
        process.kill()
        await process.wait()
        raise ToolError("GIT_TIMEOUT", "git command timed out.") from exc

    return (
        int(process.returncode or 0),
        stdout_b.decode("utf-8", errors="replace"),
        stderr_b.decode("utf-8", errors="replace"),
    )


class GitStatusTool(BaseTool):
    name = "git_status"
    description = "Show the current Git branch and working-tree status for the workspace."
    parameters = {"type": "object", "properties": {}, "required": []}

    def __init__(self, workspace: Workspace) -> None:
        self.workspace = workspace

    async def execute(self, arguments: dict[str, Any], *, on_output=None) -> ToolResult:
        code, stdout, stderr = await _git(
            self.workspace,
            "status",
            "--short",
            "--branch",
            "--untracked-files=all",
        )
        return ToolResult(
            ok=code == 0,
            summary="Git status completed." if code == 0 else "Git status failed.",
            stdout=stdout,
            stderr=stderr,
            exit_code=code,
        )


class GitDiffTool(BaseTool):
    name = "git_diff"
    description = (
        "Show a reviewable Git diff for the workspace. "
        "The structured result includes tracked changes and untracked text files. "
        "Optionally limit the diff to one workspace-relative path."
    )
    parameters = {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Optional workspace-relative file or directory path.",
            },
            "staged": {
                "type": "boolean",
                "description": "If true, show staged diff instead of unstaged diff.",
            },
        },
        "required": [],
    }

    def __init__(self, workspace: Workspace) -> None:
        self.workspace = workspace

    async def execute(self, arguments: dict[str, Any], *, on_output=None) -> ToolResult:
        args = ["diff", "--no-ext-diff", "--no-color", "--unified=3"]
        staged = bool(arguments.get("staged"))
        if staged:
            args.append("--cached")

        raw_path = arguments.get("path")
        relative_filter: str | None = None
        if raw_path:
            resolved = self.workspace.resolve(str(raw_path), must_exist=False)
            relative_filter = self.workspace.relative(resolved)
            args.extend(["--", relative_filter])

        code, stdout, stderr = await _git(self.workspace, *args)
        files = parse_unified_diff(stdout)

        if not staged and code == 0:
            untracked_args = ["ls-files", "--others", "--exclude-standard"]
            if relative_filter:
                untracked_args.extend(["--", relative_filter])
            u_code, u_stdout, u_stderr = await _git(
                self.workspace,
                *untracked_args,
            )
            if u_code != 0 and not stderr:
                stderr = u_stderr
            if u_code == 0:
                known = {str(item.get("path") or "") for item in files}
                for relative in u_stdout.splitlines():
                    relative = relative.strip()
                    if not relative or relative in known:
                        continue
                    relative_parts = Path(relative).parts
                    if any(
                        part in DEFAULT_IGNORED_DIRS
                        for part in relative_parts[:-1]
                    ):
                        continue
                    path = self.workspace.resolve(relative, must_exist=True)
                    if path.is_file():
                        files.append(
                            synthesize_untracked_file(
                                path,
                                display_path=relative.replace("\\", "/"),
                            )
                        )

        additions = sum(int(item.get("additions") or 0) for item in files)
        deletions = sum(int(item.get("deletions") or 0) for item in files)

        return ToolResult(
            ok=code == 0,
            summary=(
                f"Git diff contains {len(files)} file(s), "
                f"+{additions}/-{deletions}."
                if code == 0
                else "Git diff failed."
            ),
            stdout=stdout,
            stderr=stderr,
            exit_code=code,
            data={
                "files": files,
                "file_count": len(files),
                "additions": additions,
                "deletions": deletions,
                "staged": staged,
            },
        )


class GitLogTool(BaseTool):
    name = "git_log"
    description = "Show recent Git commits for the current workspace."
    parameters = {
        "type": "object",
        "properties": {
            "max_count": {
                "type": "integer",
                "minimum": 1,
                "maximum": 50,
                "description": "Number of commits to show. Defaults to 10.",
            },
        },
        "required": [],
    }

    def __init__(self, workspace: Workspace) -> None:
        self.workspace = workspace

    async def execute(self, arguments: dict[str, Any], *, on_output=None) -> ToolResult:
        max_count = min(max(int(arguments.get("max_count") or 10), 1), 50)
        code, stdout, stderr = await _git(
            self.workspace,
            "log",
            f"-{max_count}",
            "--date=short",
            "--pretty=format:%h %ad %s",
        )
        return ToolResult(
            ok=code == 0,
            summary="Git log completed." if code == 0 else "Git log failed.",
            stdout=stdout,
            stderr=stderr,
            exit_code=code,
        )
