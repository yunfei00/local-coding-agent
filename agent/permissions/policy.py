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
    "list_directory",
    "read_file",
    "search_files",
    "git_status",
    "git_diff",
    "git_log",
}

WORKSPACE_TOOLS = READ_ONLY_TOOLS | {
    "write_file",
    "apply_patch",
    "run_command",
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
        "git_publish",
        r"(?i)\bgit\s+push\b",
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


def command_risk(command: str) -> tuple[str, str] | None:
    for risk, pattern, reason in RISKY_COMMAND_PATTERNS:
        if re.search(pattern, command):
            return risk, reason
    return None


def _path_argument(name: str, arguments: dict[str, Any]) -> str | None:
    if name in {"list_directory", "read_file", "write_file", "apply_patch"}:
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

    def visible_tools(self, all_tools: list[str]) -> list[str]:
        allowed = (
            READ_ONLY_TOOLS
            if self.mode == PermissionMode.READ_ONLY
            else WORKSPACE_TOOLS
        )
        return sorted(name for name in all_tools if name in allowed)

    def evaluate(
        self,
        *,
        tool_name: str,
        arguments: dict[str, Any],
        workspace: Workspace,
    ) -> PermissionVerdict:
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
