from __future__ import annotations

import asyncio
import hashlib
import os
import re
from pathlib import Path
from typing import Any

from agent.persistence.store import default_data_dir

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
        data = await _structured_status(self.workspace) if code == 0 else {}
        return ToolResult(
            ok=code == 0,
            summary=(
                (
                    f"Git status: {data.get('staged_count', 0)} staged, "
                    f"{data.get('unstaged_count', 0)} unstaged, "
                    f"{data.get('untracked_count', 0)} untracked."
                )
                if code == 0
                else "Git status failed."
            ),
            stdout=stdout,
            stderr=stderr,
            exit_code=code,
            data=data,
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
        args = [
            "-c",
            "core.quotePath=false",
            "diff",
            "--no-ext-diff",
            "--no-color",
            "--find-renames",
            "--unified=3",
        ]
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

        status_counts: dict[str, int] = {}
        truncated_files: list[str] = []
        binary_files: list[str] = []
        renamed_files: list[dict[str, Any]] = []
        for item in files:
            status = str(item.get("status") or "modified")
            status_counts[status] = status_counts.get(status, 0) + 1
            path_value = str(item.get("path") or "")
            if bool(item.get("truncated")):
                truncated_files.append(path_value)
            if bool(item.get("binary")):
                binary_files.append(path_value)
            if status == "renamed":
                renamed_files.append(
                    {
                        "old_path": str(item.get("old_path") or ""),
                        "new_path": str(item.get("new_path") or path_value),
                        "similarity": item.get("similarity"),
                    }
                )

        raw_file_count = stdout.count("diff --git ")
        preview_files_truncated = raw_file_count > len(
            [item for item in files if item.get("status") != "untracked"]
        )
        review = {
            "read_only": True,
            "mode": "staged" if staged else "working_tree",
            "complete_preview": not truncated_files and not preview_files_truncated,
            "status_counts": status_counts,
            "truncated_files": truncated_files,
            "binary_files": binary_files,
            "renamed_files": renamed_files,
            "preview_files_truncated": preview_files_truncated,
            "path_filter": relative_filter,
        }

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
                "review": review,
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


_BRANCH_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]{0,119}$")
_TASK_RE = re.compile(r"[^A-Za-z0-9._-]+")


def _split_nul(value: str) -> list[str]:
    return [item for item in value.split("\x00") if item]


async def _git_name_list(
    workspace: Workspace,
    *args: str,
) -> list[str]:
    code, stdout, stderr = await _git(
        workspace,
        "-c",
        "core.quotePath=false",
        *args,
        "-z",
    )
    if code != 0:
        raise ToolError(
            "GIT_COMMAND_FAILED",
            stderr.strip() or stdout.strip() or "Git command failed.",
        )
    return _split_nul(stdout)


async def _structured_status(workspace: Workspace) -> dict[str, Any]:
    branch_code, branch_out, branch_err = await _git(
        workspace,
        "branch",
        "--show-current",
    )
    if branch_code != 0:
        raise ToolError(
            "GIT_STATUS_FAILED",
            branch_err.strip() or "Unable to read current Git branch.",
        )

    staged, unstaged, untracked = await asyncio.gather(
        _git_name_list(workspace, "diff", "--cached", "--name-only"),
        _git_name_list(workspace, "diff", "--name-only"),
        _git_name_list(
            workspace,
            "ls-files",
            "--others",
            "--exclude-standard",
        ),
    )
    return {
        "branch": branch_out.strip() or None,
        "detached": not bool(branch_out.strip()),
        "staged": staged,
        "unstaged": unstaged,
        "untracked": untracked,
        "staged_count": len(staged),
        "unstaged_count": len(unstaged),
        "untracked_count": len(untracked),
        "clean": not staged and not unstaged and not untracked,
    }


def _workspace_paths(
    workspace: Workspace,
    values: Any,
) -> list[str]:
    if not isinstance(values, list):
        raise ToolError(
            "GIT_PATHS_INVALID",
            "paths must be an array of workspace-relative paths.",
        )
    result: list[str] = []
    for raw in values:
        value = str(raw or "").strip()
        if not value:
            continue
        resolved = workspace.resolve(value, must_exist=False)
        relative = workspace.relative(resolved).replace("\\", "/")
        if relative not in result:
            result.append(relative)
    if len(result) > 200:
        raise ToolError(
            "GIT_PATHS_LIMIT",
            "At most 200 paths may be changed in one Git operation.",
        )
    return result


def _validated_branch(value: str) -> str:
    branch = str(value or "").strip()
    if (
        not branch
        or not _BRANCH_RE.fullmatch(branch)
        or ".." in branch
        or branch.endswith(("/", "."))
        or branch.startswith(("/", "."))
        or "//" in branch
        or "@{" in branch
    ):
        raise ToolError(
            "GIT_BRANCH_INVALID",
            "Git branch name is invalid or unsafe.",
        )
    return branch


def _managed_worktree_root(
    workspace: Workspace,
    *,
    create: bool = False,
) -> Path:
    digest = hashlib.sha256(
        str(workspace.root).encode("utf-8")
    ).hexdigest()[:12]
    root = default_data_dir() / "worktrees" / digest
    if create:
        root.mkdir(parents=True, exist_ok=True)
    return root.resolve(strict=False)


def _managed_worktree_path(
    workspace: Workspace,
    task_name: str,
) -> Path:
    slug = _TASK_RE.sub("-", str(task_name or "").strip()).strip("-._")
    if not slug:
        raise ToolError(
            "WORKTREE_TASK_INVALID",
            "task_name must contain at least one letter or number.",
        )
    slug = slug[:60]
    return (
        _managed_worktree_root(workspace, create=True) / slug
    ).resolve(strict=False)


async def _worktree_records(workspace: Workspace) -> list[dict[str, Any]]:
    code, stdout, stderr = await _git(
        workspace,
        "worktree",
        "list",
        "--porcelain",
    )
    if code != 0:
        raise ToolError(
            "GIT_WORKTREE_LIST_FAILED",
            stderr.strip() or "Unable to list Git worktrees.",
        )

    records: list[dict[str, Any]] = []
    current: dict[str, Any] = {}
    for line in stdout.splitlines():
        if not line.strip():
            if current:
                records.append(current)
                current = {}
            continue
        key, _, value = line.partition(" ")
        if key == "worktree":
            current["path"] = value
        elif key == "HEAD":
            current["head"] = value
        elif key == "branch":
            prefix = "refs/heads/"
            current["branch"] = (
                value[len(prefix):]
                if value.startswith(prefix)
                else value
            )
        elif key == "detached":
            current["detached"] = True
        elif key == "bare":
            current["bare"] = True
        elif key == "locked":
            current["locked"] = value or True
        elif key == "prunable":
            current["prunable"] = value or True
    if current:
        records.append(current)

    managed_root = _managed_worktree_root(workspace)
    for item in records:
        path_value = Path(str(item.get("path") or "")).resolve(strict=False)
        try:
            path_value.relative_to(managed_root)
            managed = True
        except ValueError:
            managed = False
        item["managed"] = managed
        item["current"] = path_value == workspace.root
    return records


class GitBranchesTool(BaseTool):
    name = "git_branches"
    description = "List local Git branches and identify the current branch."
    parameters = {"type": "object", "properties": {}, "required": []}

    def __init__(self, workspace: Workspace) -> None:
        self.workspace = workspace

    async def execute(self, arguments: dict[str, Any], *, on_output=None) -> ToolResult:
        code, stdout, stderr = await _git(
            self.workspace,
            "branch",
            "--format=%(refname:short)\t%(objectname:short)\t%(upstream:short)\t%(HEAD)",
        )
        if code != 0:
            return ToolResult(
                ok=False,
                summary="Git branch listing failed.",
                stdout=stdout,
                stderr=stderr,
                exit_code=code,
            )

        branches: list[dict[str, Any]] = []
        current: str | None = None
        for line in stdout.splitlines():
            name, sha, upstream, head = (line.split("\t") + ["", "", "", ""])[:4]
            if head.strip() == "*":
                current = name
            branches.append(
                {
                    "name": name,
                    "sha": sha,
                    "upstream": upstream or None,
                    "current": head.strip() == "*",
                }
            )
        return ToolResult(
            ok=True,
            summary=f"Found {len(branches)} local Git branch(es).",
            stdout=stdout,
            exit_code=0,
            data={"current_branch": current, "branches": branches},
        )


class GitStageTool(BaseTool):
    name = "git_stage"
    description = "Stage selected workspace changes, or all changes when all=true."
    parameters = {
        "type": "object",
        "properties": {
            "paths": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Workspace-relative paths to stage.",
            },
            "all": {
                "type": "boolean",
                "description": "Stage all tracked and untracked workspace changes.",
            },
        },
        "required": [],
    }

    def __init__(self, workspace: Workspace) -> None:
        self.workspace = workspace

    async def execute(self, arguments: dict[str, Any], *, on_output=None) -> ToolResult:
        stage_all = bool(arguments.get("all"))
        paths = _workspace_paths(self.workspace, arguments.get("paths") or [])
        if not stage_all and not paths:
            raise ToolError(
                "GIT_STAGE_EMPTY",
                "Provide paths or set all=true.",
            )

        args = ["add", "-A"] if stage_all else ["add", "--", *paths]
        code, stdout, stderr = await _git(self.workspace, *args)
        data = await _structured_status(self.workspace) if code == 0 else {}
        return ToolResult(
            ok=code == 0,
            summary=(
                f"Staged {data.get('staged_count', 0)} file(s)."
                if code == 0
                else "Git stage failed."
            ),
            stdout=stdout,
            stderr=stderr,
            exit_code=code,
            data=data,
        )


class GitUnstageTool(BaseTool):
    name = "git_unstage"
    description = "Unstage selected paths, or all staged paths when all=true. Working-tree edits are preserved."
    parameters = {
        "type": "object",
        "properties": {
            "paths": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Workspace-relative paths to unstage.",
            },
            "all": {
                "type": "boolean",
                "description": "Unstage every staged path.",
            },
        },
        "required": [],
    }

    def __init__(self, workspace: Workspace) -> None:
        self.workspace = workspace

    async def execute(self, arguments: dict[str, Any], *, on_output=None) -> ToolResult:
        unstage_all = bool(arguments.get("all"))
        paths = _workspace_paths(self.workspace, arguments.get("paths") or [])
        if not unstage_all and not paths:
            raise ToolError(
                "GIT_UNSTAGE_EMPTY",
                "Provide paths or set all=true.",
            )

        args = ["restore", "--staged"]
        if unstage_all:
            args.extend(["--", "."])
        else:
            args.extend(["--", *paths])
        code, stdout, stderr = await _git(self.workspace, *args)
        data = await _structured_status(self.workspace) if code == 0 else {}
        return ToolResult(
            ok=code == 0,
            summary=(
                f"{data.get('staged_count', 0)} file(s) remain staged."
                if code == 0
                else "Git unstage failed."
            ),
            stdout=stdout,
            stderr=stderr,
            exit_code=code,
            data=data,
        )


class GitCommitPrepareTool(BaseTool):
    name = "git_commit_prepare"
    description = "Review the current branch and staged changes before an explicit Git commit."
    parameters = {"type": "object", "properties": {}, "required": []}

    def __init__(self, workspace: Workspace) -> None:
        self.workspace = workspace

    async def execute(self, arguments: dict[str, Any], *, on_output=None) -> ToolResult:
        status = await _structured_status(self.workspace)
        code, stat_out, stat_err = await _git(
            self.workspace,
            "diff",
            "--cached",
            "--stat",
        )
        if code != 0:
            return ToolResult(
                ok=False,
                summary="Git commit preparation failed.",
                stderr=stat_err,
                exit_code=code,
            )
        return ToolResult(
            ok=True,
            summary=(
                f"Commit preparation: {status['staged_count']} staged file(s) "
                f"on {status['branch'] or 'detached HEAD'}."
            ),
            stdout=stat_out,
            exit_code=0,
            data={**status, "staged_stat": stat_out},
        )


class GitCommitTool(BaseTool):
    name = "git_commit"
    description = "Create a Git commit from already-staged changes. Runtime policy requires explicit current-user commit intent and approval."
    parameters = {
        "type": "object",
        "properties": {
            "message": {
                "type": "string",
                "minLength": 1,
                "maxLength": 500,
            },
        },
        "required": ["message"],
    }

    def __init__(self, workspace: Workspace) -> None:
        self.workspace = workspace

    def permission_metadata(self) -> dict[str, Any]:
        return {"source": "builtin", "risk": "git_commit"}

    async def execute(self, arguments: dict[str, Any], *, on_output=None) -> ToolResult:
        message = str(arguments.get("message") or "").strip()
        if not message:
            raise ToolError("GIT_COMMIT_MESSAGE_REQUIRED", "Commit message is required.")
        if len(message) > 500:
            raise ToolError("GIT_COMMIT_MESSAGE_TOO_LONG", "Commit message is too long.")

        before = await _structured_status(self.workspace)
        if before["staged_count"] == 0:
            raise ToolError(
                "GIT_NOTHING_STAGED",
                "No staged changes are available to commit.",
            )

        code, stdout, stderr = await _git(
            self.workspace,
            "commit",
            "-m",
            message,
            timeout=60,
        )
        after = await _structured_status(self.workspace) if code == 0 else before
        return ToolResult(
            ok=code == 0,
            summary="Git commit created." if code == 0 else "Git commit failed.",
            stdout=stdout,
            stderr=stderr,
            exit_code=code,
            data={"before": before, "after": after, "message": message},
        )


class GitWorktreeListTool(BaseTool):
    name = "git_worktree_list"
    description = "List Git worktrees and identify Local Coding Agent managed task worktrees."
    parameters = {"type": "object", "properties": {}, "required": []}

    def __init__(self, workspace: Workspace) -> None:
        self.workspace = workspace

    async def execute(self, arguments: dict[str, Any], *, on_output=None) -> ToolResult:
        worktrees = await _worktree_records(self.workspace)
        return ToolResult(
            ok=True,
            summary=f"Found {len(worktrees)} Git worktree(s).",
            data={"worktrees": worktrees},
        )


class GitWorktreeCreateTool(BaseTool):
    name = "git_worktree_create"
    description = "Create an isolated task worktree in Local Coding Agent managed storage. Requires explicit current-user worktree intent and approval."
    parameters = {
        "type": "object",
        "properties": {
            "task_name": {
                "type": "string",
                "description": "Short task name used for the managed worktree directory.",
            },
            "branch": {
                "type": "string",
                "description": "New local branch name for the task worktree.",
            },
            "base_ref": {
                "type": "string",
                "description": "Optional base ref. Defaults to HEAD.",
            },
        },
        "required": ["task_name", "branch"],
    }

    def __init__(self, workspace: Workspace) -> None:
        self.workspace = workspace

    def permission_metadata(self) -> dict[str, Any]:
        return {"source": "builtin", "risk": "git_worktree_create"}

    async def execute(self, arguments: dict[str, Any], *, on_output=None) -> ToolResult:
        branch = _validated_branch(str(arguments.get("branch") or ""))
        task_name = str(arguments.get("task_name") or "").strip()
        base_ref = str(arguments.get("base_ref") or "HEAD").strip() or "HEAD"
        target = _managed_worktree_path(self.workspace, task_name)
        if target.exists():
            raise ToolError(
                "WORKTREE_PATH_EXISTS",
                f"Managed worktree path already exists: {target}",
            )

        code, stdout, stderr = await _git(
            self.workspace,
            "worktree",
            "add",
            "-b",
            branch,
            str(target),
            base_ref,
            timeout=60,
        )
        if code != 0:
            return ToolResult(
                ok=False,
                summary="Task worktree creation failed.",
                stdout=stdout,
                stderr=stderr,
                exit_code=code,
            )
        worktrees = await _worktree_records(self.workspace)
        return ToolResult(
            ok=True,
            summary=f"Created task worktree for branch {branch}.",
            stdout=stdout,
            exit_code=0,
            data={
                "path": str(target),
                "branch": branch,
                "base_ref": base_ref,
                "managed": True,
                "worktrees": worktrees,
            },
        )


class GitWorktreeRemoveTool(BaseTool):
    name = "git_worktree_remove"
    description = "Remove a clean Local Coding Agent managed worktree. Dirty worktrees are refused."
    parameters = {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Absolute managed worktree path returned by git_worktree_list/create.",
            },
        },
        "required": ["path"],
    }

    def __init__(self, workspace: Workspace) -> None:
        self.workspace = workspace

    def permission_metadata(self) -> dict[str, Any]:
        return {"source": "builtin", "risk": "git_worktree_remove"}

    async def execute(self, arguments: dict[str, Any], *, on_output=None) -> ToolResult:
        raw_path = str(arguments.get("path") or "").strip()
        if not raw_path:
            raise ToolError("WORKTREE_PATH_REQUIRED", "Worktree path is required.")

        target = Path(raw_path).expanduser().resolve(strict=False)
        managed_root = _managed_worktree_root(self.workspace)
        try:
            target.relative_to(managed_root)
        except ValueError as exc:
            raise ToolError(
                "WORKTREE_NOT_MANAGED",
                "Only Local Coding Agent managed worktrees can be removed here.",
            ) from exc
        if target == self.workspace.root:
            raise ToolError(
                "WORKTREE_ACTIVE_WORKSPACE",
                "The currently active workspace cannot remove itself.",
            )
        if not target.exists():
            raise ToolError(
                "WORKTREE_NOT_FOUND",
                f"Worktree path does not exist: {target}",
            )

        try:
            process = await asyncio.create_subprocess_exec(
                "git",
                "-C",
                str(target),
                "status",
                "--porcelain",
                "--untracked-files=all",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            dirty_out, dirty_err = await asyncio.wait_for(
                process.communicate(),
                timeout=30,
            )
        except asyncio.TimeoutError as exc:
            process.kill()
            await process.wait()
            raise ToolError(
                "GIT_TIMEOUT",
                "Git dirty-worktree check timed out.",
            ) from exc

        dirty = dirty_out.decode("utf-8", errors="replace").strip()
        if process.returncode != 0:
            raise ToolError(
                "WORKTREE_STATUS_FAILED",
                dirty_err.decode("utf-8", errors="replace").strip()
                or "Unable to inspect worktree status.",
            )
        if dirty:
            raise ToolError(
                "WORKTREE_DIRTY",
                "Worktree has uncommitted changes and will not be removed.",
            )

        code, stdout, stderr = await _git(
            self.workspace,
            "worktree",
            "remove",
            str(target),
            timeout=60,
        )
        if code != 0:
            return ToolResult(
                ok=False,
                summary="Task worktree removal failed.",
                stdout=stdout,
                stderr=stderr,
                exit_code=code,
            )
        return ToolResult(
            ok=True,
            summary=f"Removed task worktree {target.name}.",
            stdout=stdout,
            exit_code=0,
            data={"path": str(target), "removed": True},
        )
