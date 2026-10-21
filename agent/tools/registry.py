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
from agent.tools.shell import RunCommandTool
from agent.tools.workspace import Workspace


class ToolRegistry:
    def __init__(
        self,
        workspace: Workspace,
        *,
        extra_tools: Iterable[BaseTool] = (),
    ) -> None:
        tools: list[BaseTool] = [
            FileExistsTool(workspace),
            ListDirectoryTool(workspace),
            ReadFileTool(workspace),
            SearchFilesTool(workspace),
            WriteFileTool(workspace),
            ApplyPatchTool(workspace),
            RunCommandTool(workspace),
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
        for tool in [*tools, *list(extra_tools)]:
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
    ) -> list[dict[str, Any]]:
        if allowed_names is None:
            names = self.names
        else:
            allowed = set(allowed_names)
            names = [name for name in self.names if name in allowed]
        return [self._tools[name].ollama_schema() for name in names]

    async def execute(
        self,
        name: str,
        arguments: dict[str, Any],
        *,
        on_output: OutputCallback | None = None,
    ) -> ToolResult:
        tool = self._tools.get(name)
        if not tool:
            raise ToolError("TOOL_NOT_FOUND", f"Unknown tool: {name}")
        return await tool.execute(arguments, on_output=on_output)
