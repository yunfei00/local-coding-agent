from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from agent.tools.base import BaseTool, OutputCallback, ToolError, ToolResult
from agent.tools.filesystem import (
    ApplyPatchTool,
    FileExistsTool,
    ListDirectoryTool,
    ReadFileTool,
    SearchFilesTool,
    WriteFileTool,
)
from agent.tools.git import (
    GitBranchesTool,
    GitCommitPrepareTool,
    GitCommitTool,
    GitDiffTool,
    GitLogTool,
    GitStageTool,
    GitStatusTool,
    GitUnstageTool,
    GitWorktreeCreateTool,
    GitWorktreeListTool,
    GitWorktreeRemoveTool,
)
from agent.tools.shell import RunCommandTool, StartProcessTool, ReadProcessTool, StopProcessTool
from agent.tools.processes import ProcessManager
from agent.desktop.runtime import DesktopRuntime, NAMES as DESKTOP_TOOLS
from agent.tools.desktop import desktop_tools
from agent.tools.workspace import Workspace


class ToolRegistry:
    def __init__(
        self,
        workspace: Workspace,
        *,
        extra_tools: Iterable[BaseTool] = (),
    ) -> None:
        self.processes = ProcessManager(workspace)
        self.desktop = DesktopRuntime()
        tools: list[BaseTool] = [
            FileExistsTool(workspace),
            ListDirectoryTool(workspace),
            ReadFileTool(workspace),
            SearchFilesTool(workspace),
            WriteFileTool(workspace),
            ApplyPatchTool(workspace),
            RunCommandTool(workspace, self.processes),
            StartProcessTool(workspace, self.processes),
            ReadProcessTool(self.processes),
            StopProcessTool(self.processes),
            GitStatusTool(workspace),
            GitDiffTool(workspace),
            GitLogTool(workspace),
            GitBranchesTool(workspace),
            GitStageTool(workspace),
            GitUnstageTool(workspace),
            GitCommitPrepareTool(workspace),
            GitCommitTool(workspace),
            GitWorktreeListTool(workspace),
            GitWorktreeCreateTool(workspace),
            GitWorktreeRemoveTool(workspace),
        ]
        self._tools: dict[str, BaseTool] = {}
        for tool in [*tools, *desktop_tools(self.desktop), *list(extra_tools)]:
            self.register(tool)

    def register(
        self,
        tool: BaseTool,
        *,
        replace: bool = False,
    ) -> None:
        if tool.name in self._tools and not replace:
            raise ToolError(
                "TOOL_NAME_COLLISION",
                f"Tool already registered: {tool.name}",
            )
        self._tools[tool.name] = tool

    def unregister(self, name: str) -> None:
        self._tools.pop(name, None)

    @property
    def names(self) -> list[str]:
        return sorted(self._tools)

    def permission_metadata(
        self,
        name: str,
    ) -> dict[str, Any]:
        tool = self._tools.get(name)
        if not tool:
            return {}
        return tool.permission_metadata()

    def permission_metadata_map(self) -> dict[str, dict[str, Any]]:
        return {
            name: tool.permission_metadata()
            for name, tool in self._tools.items()
        }

    def unregister_prefix(self, prefix: str) -> None:
        for name in list(self._tools):
            if name.startswith(prefix):
                self._tools.pop(name, None)

    def schemas(
        self,
        allowed_names: Iterable[str] | None = None,
        *, desktop_owner_id: str | None = None,
    ) -> list[dict[str, Any]]:
        if allowed_names is None:
            names = self.names
        else:
            allowed = set(allowed_names)
            names = [name for name in self.names if name in allowed]
        if desktop_owner_id is not None and not any(v['owner']==desktop_owner_id for v in self.desktop.windows.values()):
            # Other desktop tools require a live window_id. Discover them after
            # enumeration, without burdening ordinary coding turns with UI schemas.
            names=[n for n in names if n not in DESKTOP_TOOLS or n=='desktop_list_windows']
        return [self._tools[name].ollama_schema() for name in names]

    async def execute(
        self,
        name: str,
        arguments: dict[str, Any],
        *,
        on_output: OutputCallback | None = None,
        on_raw_output=None,
        environment=None,
        owner_id="",
        desktop_authorized=False,
        supports_vision=False,
    ) -> ToolResult:
        tool = self._tools.get(name)
        if not tool:
            raise ToolError("TOOL_NOT_FOUND", f"Unknown tool: {name}")
        if name in DESKTOP_TOOLS:
            return await tool.execute(arguments, owner_id=owner_id, desktop_authorized=desktop_authorized, supports_vision=supports_vision)
        if name == "run_command":
            return await tool.execute(arguments, on_output=on_output, on_raw_output=on_raw_output, environment=environment, owner_id=owner_id)
        if name in {"start_process", "read_process", "stop_process"}:
            return await tool.execute(arguments, on_output=on_output, owner_id=owner_id)
        return await tool.execute(arguments, on_output=on_output)
