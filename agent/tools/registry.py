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
from agent.tools.git import GitDiffTool, GitLogTool, GitStatusTool
from agent.tools.shell import RunCommandTool
from agent.tools.workspace import Workspace


class ToolRegistry:
    def __init__(self, workspace: Workspace) -> None:
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
        ]
        self._tools = {tool.name: tool for tool in tools}

    @property
    def names(self) -> list[str]:
        return sorted(self._tools)

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
