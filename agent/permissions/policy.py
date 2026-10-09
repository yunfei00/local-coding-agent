from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any

from agent.tools.workspace import Workspace


class PermissionMode(StrEnum):
    READ_ONLY = "read_only"
    WORKSPACE = "workspace"
    FULL_ACCESS = "full_access"


READ_ONLY_TOOLS = {
    "file_exists",
    "list_directory",
    "read_file",
    "search_files",
    "git_status",
    "git_diff",
    "git_log",
    "git_branches",
    "git_commit_prepare",
    "git_worktree_list",
}

WORKSPACE_TOOLS = READ_ONLY_TOOLS | {
    "write_file",
    "apply_patch",
    "run_command",
    "git_stage",
    "git_unstage",
    "git_commit",
    "git_worktree_create",
    "git_worktree_remove",
}


RISKY_COMMAND_PATTERNS: list[tuple[str, str, str]] = [
    (
        "delete",
        r"(?i)(?:^|[;&|]\s*)(?:remove-item|del|erase|rmdir)\b|\brd\s+/s\b|\brm\s+-",
        "Command may delete files or directories.",
    ),
    (
        "git_destructive",
        r"(?i)\bgit\s+(?:reset\s+--hard|clean\s+-|checkout\s+--|restore\b)",
        "Command may discard or overwrite working-tree changes.",
    ),
    (
        "git_commit",
        r"(?i)\bgit\b[^\r\n;&|]*\bcommit\b",
        "Command creates a Git commit and requires explicit user approval.",
    ),
    (
        "git_publish",
        r"(?i)\bgit\b[^\r\n;&|]*\bpush\b",
        "Command publishes local Git changes to a remote repository.",
    ),
    (
        "system_admin",
        r"(?i)\b(?:format|shutdown|restart-computer|stop-computer)\b|\breg\s+(?:add|delete)\b",
        "Command can change or stop the operating system.",
    ),
]


@dataclass(frozen=True)
class PermissionVerdict:
    allowed: bool
    requires_approval: bool = False
    reason: str = ""
    approval_key: str | None = None
    risk: str = "normal"


def parse_permission_mode(value: str | PermissionMode) -> PermissionMode:
    if isinstance(value, PermissionMode):
        return value
    try:
        return PermissionMode(value)
    except ValueError as exc:
        raise ValueError(f"Unknown permission mode: {value}") from exc


_NEGATED_COMMIT = re.compile(
    r"(?i)(?:do\s+not|don't|dont|不要|别|无需|不需要).{0,12}(?:git\s+commit|commit|提交)"
)
_NEGATED_PUSH = re.compile(
    r"(?i)(?:do\s+not|don't|dont|不要|别|无需|不需要).{0,12}(?:git\s+push|push|推送)"
)
_NEGATED_WORKTREE = re.compile(
    r"(?i)(?:do\s+not|don't|dont|不要|别|无需|不需要).{0,16}(?:worktree|工作树|独立工作区)"
)


def explicit_git_intent(prompt: str | None, action: str) -> bool:
    text = str(prompt or "").strip()
    if not text:
        return False

    if action == "commit":
        if _NEGATED_COMMIT.search(text):
            return False
        return bool(
            re.search(r"(?i)\bgit\s+commit\b|\bcommit\b", text)
            or re.search(r"(?:提交代码|创建提交|做一个提交|提交这些改动|提交当前改动)", text)
        )

    if action == "push":
        if _NEGATED_PUSH.search(text):
            return False
        return bool(
            re.search(r"(?i)\bgit\s+push\b|\bpush\b", text)
            or re.search(r"(?:推送到|推到远程|推送代码|推送提交)", text)
        )

    if action == "worktree":
        if _NEGATED_WORKTREE.search(text):
            return False
        return bool(
            re.search(r"(?i)\bworktree\b", text)
            or re.search(r"(?:工作树|独立工作区|隔离工作区)", text)
        )

    return False


def command_risk(command: str) -> tuple[str, str] | None:
    for risk, pattern, reason in RISKY_COMMAND_PATTERNS:
        if re.search(pattern, command):
            return risk, reason
    return None


def _path_argument(name: str, arguments: dict[str, Any]) -> str | None:
    if name in {"file_exists", "list_directory", "read_file", "write_file", "apply_patch"}:
        value = arguments.get("path")
        return str(value) if value is not None else "."
    if name == "search_files":
        return str(arguments.get("path") or ".")
    if name == "run_command":
        return str(arguments.get("cwd") or ".")
    if name == "git_diff" and arguments.get("path"):
        return str(arguments["path"])
    return None


def _is_outside_workspace(
    workspace: Workspace,
    value: str | None,
) -> bool:
    if value is None:
        return False
    return not workspace.contains(Path(value).expanduser())


def command_external_reference(
    workspace: Workspace,
    command: str,
) -> str | None:
    if re.search(r"(?:^|[\\/])\.\.(?:[\\/]|$)", command):
        return "Command contains a parent-directory path that can escape the workspace."

    candidates: list[str] = []
    candidates.extend(
        match.group(0)
        for match in re.finditer(
            r"(?i)(?<![A-Za-z0-9_])[A-Za-z]:[\\/][^\s\"';&|]+",
            command,
        )
    )
    if os.name != "nt":
        candidates.extend(
            match.group(0)
            for match in re.finditer(
                r"(?<![A-Za-z0-9_])/(?:[^\s\"';&|]+/?)+",
                command,
            )
        )

    for candidate in candidates:
        if not workspace.contains(candidate):
            return f"Command references a path outside the workspace: {candidate}"

    return None


class PermissionPolicy:
    def __init__(self, mode: PermissionMode = PermissionMode.WORKSPACE) -> None:
        self.mode = mode

    @property
    def available_modes(self) -> list[str]:
        return [mode.value for mode in PermissionMode]

    def set_mode(self, mode: str | PermissionMode) -> PermissionMode:
        self.mode = parse_permission_mode(mode)
        return self.mode

    def visible_tools(
        self,
        all_tools: list[str],
        tool_metadata: dict[str, dict[str, Any]] | None = None,
    ) -> list[str]:
        metadata = tool_metadata or {}
        visible: list[str] = []
        for name in all_tools:
            item = metadata.get(name) or {}
            if item.get("source") == "mcp":
                if self.mode == PermissionMode.READ_ONLY:
                    if item.get("trusted") and item.get("read_only"):
                        visible.append(name)
                else:
                    visible.append(name)
                continue

            allowed = (
                READ_ONLY_TOOLS
                if self.mode == PermissionMode.READ_ONLY
                else WORKSPACE_TOOLS
            )
            if name in allowed:
                visible.append(name)
        return sorted(visible)

    def evaluate(
        self,
        *,
        tool_name: str,
        arguments: dict[str, Any],
        workspace: Workspace,
        tool_metadata: dict[str, Any] | None = None,
        user_prompt: str | None = None,
    ) -> PermissionVerdict:
        metadata = tool_metadata or {}
        if metadata.get("source") == "mcp":
            trusted = bool(metadata.get("trusted"))
            read_only = bool(metadata.get("read_only"))
            risk = str(metadata.get("risk") or "mcp_mutating")
            server = str(metadata.get("server") or "unknown")

            if self.mode == PermissionMode.READ_ONLY:
                if trusted and read_only:
                    return PermissionVerdict(allowed=True)
                return PermissionVerdict(
                    allowed=False,
                    reason=(
                        "MCP tool is not available in Read Only mode unless "
                        "its server is trusted and the tool is locally classified "
                        "as read-only."
                    ),
                    risk="read_only",
                )

            if trusted and read_only:
                return PermissionVerdict(allowed=True)

            if risk == "git_commit" and not explicit_git_intent(
                user_prompt,
                "commit",
            ):
                return PermissionVerdict(
                    allowed=False,
                    reason=(
                        "Git commit through MCP requires an explicit request "
                        "in the current user message."
                    ),
                    risk="git_commit_intent",
                )
            if risk == "git_publish" and not explicit_git_intent(
                user_prompt,
                "push",
            ):
                return PermissionVerdict(
                    allowed=False,
                    reason=(
                        "Git push through MCP requires an explicit request "
                        "in the current user message."
                    ),
                    risk="git_publish_intent",
                )

            fingerprint = json.dumps(
                {
                    "tool": tool_name,
                    "server": server,
                    "arguments": arguments,
                    "risk": risk,
                },
                sort_keys=True,
                ensure_ascii=False,
                default=str,
            )
            return PermissionVerdict(
                allowed=True,
                requires_approval=True,
                reason=(
                    f"MCP tool from server '{server}' is not classified as "
                    "trusted read-only and requires explicit approval."
                ),
                approval_key="mcp:" + fingerprint,
                risk=risk,
            )

        if tool_name == "git_commit":
            if not explicit_git_intent(user_prompt, "commit"):
                return PermissionVerdict(
                    allowed=False,
                    reason=(
                        "Git commit requires an explicit request in the current "
                        "user message. Approval alone is not sufficient."
                    ),
                    risk="git_commit_intent",
                )
            fingerprint = json.dumps(
                {"tool": tool_name, "arguments": arguments},
                sort_keys=True,
                ensure_ascii=False,
                default=str,
            )
            return PermissionVerdict(
                allowed=True,
                requires_approval=True,
                reason="Git commit was explicitly requested and requires approval.",
                approval_key="git_commit:" + fingerprint,
                risk="git_commit",
            )

        if tool_name in {"git_worktree_create", "git_worktree_remove"}:
            if not explicit_git_intent(user_prompt, "worktree"):
                return PermissionVerdict(
                    allowed=False,
                    reason=(
                        "Worktree creation/removal requires an explicit request "
                        "in the current user message."
                    ),
                    risk="git_worktree_intent",
                )
            fingerprint = json.dumps(
                {"tool": tool_name, "arguments": arguments},
                sort_keys=True,
                ensure_ascii=False,
                default=str,
            )
            return PermissionVerdict(
                allowed=True,
                requires_approval=True,
                reason=(
                    "This changes Git worktree state in Local Coding Agent "
                    "managed storage and requires approval."
                ),
                approval_key="git_worktree:" + fingerprint,
                risk=(
                    "git_worktree_create"
                    if tool_name == "git_worktree_create"
                    else "git_worktree_remove"
                ),
            )

        if tool_name not in WORKSPACE_TOOLS:
            return PermissionVerdict(
                allowed=False,
                reason=f"Tool is not permitted: {tool_name}",
                risk="unknown_tool",
            )

        if self.mode == PermissionMode.READ_ONLY and tool_name not in READ_ONLY_TOOLS:
            return PermissionVerdict(
                allowed=False,
                reason=(
                    f"{tool_name} is disabled in Read Only mode. "
                    "Change the permission mode before modifying or executing."
                ),
                risk="read_only",
            )

        path_value = _path_argument(tool_name, arguments)
        outside = _is_outside_workspace(workspace, path_value)
        if outside:
            if self.mode != PermissionMode.FULL_ACCESS:
                return PermissionVerdict(
                    allowed=False,
                    reason=(
                        "The requested path is outside the active workspace. "
                        "Use Full Access mode if project-external access is required."
                    ),
                    risk="outside_workspace",
                )

            normalized = str(Path(path_value or "").expanduser().resolve(strict=False))
            return PermissionVerdict(
                allowed=True,
                requires_approval=True,
                reason=(
                    "This action accesses a path outside the active workspace: "
                    + normalized
                ),
                approval_key=f"outside:{tool_name}:{normalized}",
                risk="outside_workspace",
            )

        if tool_name == "run_command":
            command = str(arguments.get("command") or "")
            external_reason = command_external_reference(workspace, command)
            if external_reason:
                if self.mode != PermissionMode.FULL_ACCESS:
                    return PermissionVerdict(
                        allowed=False,
                        reason=(
                            external_reason
                            + " Use Full Access mode if this is intentional."
                        ),
                        risk="outside_workspace",
                    )
                return PermissionVerdict(
                    allowed=True,
                    requires_approval=True,
                    reason=external_reason,
                    approval_key="command:outside:" + command,
                    risk="outside_workspace",
                )

            risky = command_risk(command)
            if risky:
                risk, reason = risky
                if risk == "git_commit" and not explicit_git_intent(
                    user_prompt,
                    "commit",
                ):
                    return PermissionVerdict(
                        allowed=False,
                        reason=(
                            "Git commit requires an explicit request in the "
                            "current user message. Approval alone is not sufficient."
                        ),
                        risk="git_commit_intent",
                    )
                if risk == "git_publish" and not explicit_git_intent(
                    user_prompt,
                    "push",
                ):
                    return PermissionVerdict(
                        allowed=False,
                        reason=(
                            "Git push requires an explicit request in the "
                            "current user message. Approval alone is not sufficient."
                        ),
                        risk="git_publish_intent",
                    )
                fingerprint = json.dumps(
                    {"risk": risk, "command": command},
                    sort_keys=True,
                    ensure_ascii=False,
                )
                return PermissionVerdict(
                    allowed=True,
                    requires_approval=True,
                    reason=reason,
                    approval_key="command:" + fingerprint,
                    risk=risk,
                )

        return PermissionVerdict(allowed=True)
