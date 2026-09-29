from __future__ import annotations

from typing import Any

from agent.tools.base import BaseTool, OutputCallback, ToolError, ToolResult
from agent.tools.filesystem import (
    ApplyPatchTool,
    ListDirectoryTool,
    ReadFileTool,
    SearchFilesTool,
    WriteFileTool,
)
from agent.tools.git import GitDiffTool, GitLogTool, GitStatusTool
from agent.tools.shell import RunCommandTool
from agent.tools.workspace import Workspace


class ToolRegistry:
    def __init__(self, workspace: Workspace) -> None:
        tools: list[BaseTool] = [
            ListDirectoryTool(workspace),
            ReadFileTool(workspace),
            SearchFilesTool(workspace),
            WriteFileTool(workspace),
            ApplyPatchTool(workspace),
            RunCommandTool(workspace),
            GitStatusTool(workspace),
            GitDiffTool(workspace),
            GitLogTool(workspace),
        ]
        self._tools = {tool.name: tool for tool in tools}

    @property
    def names(self) -> list[str]:
        return sorted(self._tools)

    def schemas(self) -> list[dict[str, Any]]:
        return [self._tools[name].ollama_schema() for name in self.names]

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
