from __future__ import annotations

import fnmatch
import re
from pathlib import Path
from typing import Any

from agent.tools.base import BaseTool, ToolError, ToolResult
from agent.tools.workspace import DEFAULT_IGNORED_DIRS, Workspace


MAX_READ_BYTES = 512 * 1024
MAX_SEARCH_FILE_BYTES = 2 * 1024 * 1024
MAX_SEARCH_RESULTS = 200


def _is_probably_binary(path: Path) -> bool:
    try:
        with path.open("rb") as handle:
            sample = handle.read(4096)
    except OSError:
        return False
    return b"\x00" in sample


class FileExistsTool(BaseTool):
    name = "file_exists"
    description = (
        "Check whether a file or directory exists without reading its contents. "
        "Useful for detecting project manifests, wrappers and optional configuration."
    )
    parameters = {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "File or directory path; workspace-relative is preferred.",
            },
        },
        "required": ["path"],
    }

    def __init__(self, workspace: Workspace) -> None:
        self.workspace = workspace

    async def execute(self, arguments: dict[str, Any], *, on_output=None) -> ToolResult:
        path = self.workspace.resolve(str(arguments["path"]), must_exist=False)
        exists = path.exists()
        kind = (
            "directory"
            if exists and path.is_dir()
            else "file"
            if exists and path.is_file()
            else None
        )
        display = self.workspace.display(path)
        return ToolResult(
            ok=True,
            summary=(
                f"{display} exists ({kind})."
                if exists
                else f"{display} does not exist."
            ),
            data={
                "path": display,
                "exists": exists,
                "type": kind,
            },
        )


class ListDirectoryTool(BaseTool):
    name = "list_directory"
    description = (
        "List files and directories. Use a workspace-relative path normally. "
        "Absolute paths outside the workspace require Full Access and explicit approval."
    )
    parameters = {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Directory path. Use '.' for the workspace root.",
            },
            "max_entries": {
                "type": "integer",
                "minimum": 1,
                "maximum": 500,
                "description": "Maximum number of entries to return.",
            },
        },
        "required": [],
    }

    def __init__(self, workspace: Workspace) -> None:
        self.workspace = workspace

    async def execute(self, arguments: dict[str, Any], *, on_output=None) -> ToolResult:
        path = self.workspace.resolve(str(arguments.get("path") or "."), must_exist=True)
        if not path.is_dir():
            raise ToolError("NOT_DIRECTORY", f"Not a directory: {self.workspace.relative(path)}")

        max_entries = min(max(int(arguments.get("max_entries") or 200), 1), 500)
        entries = []
        for child in sorted(path.iterdir(), key=lambda item: (not item.is_dir(), item.name.lower())):
            relative = self.workspace.relative(child)
            entries.append(
                {
                    "name": child.name,
                    "path": relative,
                    "type": "directory" if child.is_dir() else "file",
                    "size": child.stat().st_size if child.is_file() else None,
                }
            )
            if len(entries) >= max_entries:
                break

        return ToolResult(
            ok=True,
            summary=f"Listed {len(entries)} entries in {self.workspace.relative(path) or '.'}.",
            data={"path": self.workspace.relative(path), "entries": entries},
        )


class ReadFileTool(BaseTool):
    name = "read_file"
    description = (
        "Read a UTF-8 text file. Use a workspace-relative path normally. "
        "Absolute paths outside the workspace require Full Access and approval. "
        "Use start_line/end_line to avoid reading a very large file all at once."
    )
    parameters = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "File path; workspace-relative is preferred."},
            "start_line": {"type": "integer", "minimum": 1},
            "end_line": {"type": "integer", "minimum": 1},
        },
        "required": ["path"],
    }

    def __init__(self, workspace: Workspace) -> None:
        self.workspace = workspace

    async def execute(self, arguments: dict[str, Any], *, on_output=None) -> ToolResult:
        path = self.workspace.resolve(str(arguments["path"]), must_exist=True)
        if not path.is_file():
            raise ToolError("NOT_FILE", f"Not a file: {self.workspace.relative(path)}")
        if path.stat().st_size > MAX_READ_BYTES and "end_line" not in arguments:
            raise ToolError(
                "FILE_TOO_LARGE",
                "File is larger than 512 KiB. Read a line range instead.",
            )
        if _is_probably_binary(path):
            raise ToolError("BINARY_FILE", "Binary files cannot be read as text.")

        text = path.read_text(encoding="utf-8", errors="replace")
        lines = text.splitlines()
        start = max(int(arguments.get("start_line") or 1), 1)
        end = int(arguments.get("end_line") or len(lines))
        end = min(max(end, start), len(lines)) if lines else 0
        selected = lines[start - 1 : end] if lines else []
        numbered = "\n".join(
            f"{line_no:>6}: {line}"
            for line_no, line in enumerate(selected, start=start)
        )

        return ToolResult(
            ok=True,
            summary=f"Read {self.workspace.relative(path)} lines {start}-{end}.",
            data={
                "path": self.workspace.relative(path),
                "start_line": start,
                "end_line": end,
                "total_lines": len(lines),
                "content": numbered,
            },
        )


class WriteFileTool(BaseTool):
    name = "write_file"
    description = (
        "Create or replace a UTF-8 text file. Use a workspace-relative path normally. "
        "Absolute paths outside the workspace require Full Access and approval. "
        "Prefer apply_patch for small edits to existing files."
    )
    parameters = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Workspace-relative file path."},
            "content": {"type": "string", "description": "Complete UTF-8 file content."},
        },
        "required": ["path", "content"],
    }

    def __init__(self, workspace: Workspace) -> None:
        self.workspace = workspace

    async def execute(self, arguments: dict[str, Any], *, on_output=None) -> ToolResult:
        path = self.workspace.resolve(str(arguments["path"]), must_exist=False)
        if path.exists() and path.is_dir():
            raise ToolError("IS_DIRECTORY", "Cannot overwrite a directory with a file.")

        content = str(arguments["content"])
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

        relative = self.workspace.relative(path)
        return ToolResult(
            ok=True,
            summary=f"Wrote {relative} ({len(content.encode('utf-8'))} bytes).",
            data={"path": relative},
            changed_paths=[relative],
        )


class ApplyPatchTool(BaseTool):
    name = "apply_patch"
    description = (
        "Make a precise text edit by replacing exact old_text with new_text. "
        "The edit fails if old_text is missing or occurs multiple times unless replace_all is true."
    )
    parameters = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Workspace-relative text file path."},
            "old_text": {"type": "string", "description": "Exact existing text to replace."},
            "new_text": {"type": "string", "description": "Replacement text."},
            "replace_all": {
                "type": "boolean",
                "description": "Replace all exact occurrences. Defaults to false.",
            },
        },
        "required": ["path", "old_text", "new_text"],
    }

    def __init__(self, workspace: Workspace) -> None:
        self.workspace = workspace

    async def execute(self, arguments: dict[str, Any], *, on_output=None) -> ToolResult:
        path = self.workspace.resolve(str(arguments["path"]), must_exist=True)
        if not path.is_file():
            raise ToolError("NOT_FILE", "Patch target is not a file.")
        if _is_probably_binary(path):
            raise ToolError("BINARY_FILE", "Binary files cannot be patched as text.")

        old_text = str(arguments["old_text"])
        new_text = str(arguments["new_text"])
        if not old_text:
            raise ToolError("EMPTY_OLD_TEXT", "old_text cannot be empty.")

        content = path.read_text(encoding="utf-8", errors="strict")
        count = content.count(old_text)
        if count == 0:
            raise ToolError("PATCH_NOT_FOUND", "old_text was not found in the target file.")

        replace_all = bool(arguments.get("replace_all", False))
        if count > 1 and not replace_all:
            raise ToolError(
                "PATCH_AMBIGUOUS",
                f"old_text occurs {count} times. Provide more context or set replace_all.",
            )

        updated = content.replace(old_text, new_text) if replace_all else content.replace(old_text, new_text, 1)
        path.write_text(updated, encoding="utf-8")
        relative = self.workspace.relative(path)

        return ToolResult(
            ok=True,
            summary=f"Patched {relative}; replaced {count if replace_all else 1} occurrence(s).",
            data={"path": relative, "occurrences": count if replace_all else 1},
            changed_paths=[relative],
        )


class SearchFilesTool(BaseTool):
    name = "search_files"
    description = (
        "Search workspace text files using literal text or a regular expression. "
        "Supports path/file globs, custom excludes, context lines and bounded results. "
        "An absolute search path outside the workspace requires Full Access and approval."
    )
    parameters = {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Literal text or regular expression to search for.",
            },
            "path": {
                "type": "string",
                "description": "Workspace-relative directory to search. Defaults to '.'.",
            },
            "glob": {
                "type": "string",
                "description": (
                    "Optional file/path glob such as '*.py', 'src/**/*.ts' or "
                    "'**/CMakeLists.txt'."
                ),
            },
            "regex": {
                "type": "boolean",
                "description": "Interpret query as a regular expression. Defaults to false.",
            },
            "exclude": {
                "type": "array",
                "items": {"type": "string"},
                "description": (
                    "Optional glob patterns to exclude, for example "
                    "['generated/**', '*.min.js']."
                ),
            },
            "case_sensitive": {
                "type": "boolean",
                "description": "Defaults to false.",
            },
            "context_before": {
                "type": "integer",
                "minimum": 0,
                "maximum": 20,
                "description": "Lines of context before each match. Defaults to 0.",
            },
            "context_after": {
                "type": "integer",
                "minimum": 0,
                "maximum": 20,
                "description": "Lines of context after each match. Defaults to 0.",
            },
            "max_results": {
                "type": "integer",
                "minimum": 1,
                "maximum": 200,
            },
        },
        "required": ["query"],
    }

    def __init__(self, workspace: Workspace) -> None:
        self.workspace = workspace

    @staticmethod
    def _matches_pattern(relative: str, name: str, pattern: str) -> bool:
        normalized = pattern.replace("\\", "/")
        return fnmatch.fnmatch(relative, normalized) or fnmatch.fnmatch(
            name,
            normalized,
        )

    async def execute(self, arguments: dict[str, Any], *, on_output=None) -> ToolResult:
        query = str(arguments["query"])
        if not query:
            raise ToolError("EMPTY_QUERY", "Search query cannot be empty.")

        root = self.workspace.resolve(
            str(arguments.get("path") or "."),
            must_exist=True,
        )
        if not root.is_dir():
            raise ToolError("NOT_DIRECTORY", "Search path must be a directory.")

        filename_glob = str(arguments.get("glob") or "*").strip() or "*"
        use_regex = bool(arguments.get("regex", False))
        case_sensitive = bool(arguments.get("case_sensitive", False))
        context_before = min(
            max(int(arguments.get("context_before") or 0), 0),
            20,
        )
        context_after = min(
            max(int(arguments.get("context_after") or 0), 0),
            20,
        )
        max_results = min(
            max(int(arguments.get("max_results") or 50), 1),
            MAX_SEARCH_RESULTS,
        )

        raw_excludes = arguments.get("exclude") or []
        if not isinstance(raw_excludes, list):
            raise ToolError("INVALID_EXCLUDE", "exclude must be an array of glob patterns.")
        excludes = [
            str(item).strip()
            for item in raw_excludes
            if str(item).strip()
        ]

        flags = 0 if case_sensitive else re.IGNORECASE
        if use_regex:
            try:
                matcher = re.compile(query, flags)
            except re.error as exc:
                raise ToolError(
                    "INVALID_REGEX",
                    f"Invalid regular expression: {exc}",
                ) from exc
        else:
            needle = query if case_sensitive else query.lower()
            matcher = None

        results: list[dict[str, Any]] = []
        scanned_files = 0
        skipped_files = 0
        truncated = False

        candidates = sorted(
            root.rglob("*"),
            key=lambda item: item.relative_to(root).as_posix().lower(),
        )

        for path in candidates:
            if not path.is_file():
                continue

            relative_from_root = path.relative_to(root).as_posix()
            parts = path.relative_to(root).parts
            if any(part in DEFAULT_IGNORED_DIRS for part in parts[:-1]):
                skipped_files += 1
                continue
            if not self._matches_pattern(
                relative_from_root,
                path.name,
                filename_glob,
            ):
                continue
            if any(
                self._matches_pattern(relative_from_root, path.name, pattern)
                for pattern in excludes
            ):
                skipped_files += 1
                continue

            try:
                if (
                    path.stat().st_size > MAX_SEARCH_FILE_BYTES
                    or _is_probably_binary(path)
                ):
                    skipped_files += 1
                    continue
                text_value = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                skipped_files += 1
                continue

            scanned_files += 1
            lines = text_value.splitlines()

            for index, line in enumerate(lines):
                matched = (
                    bool(matcher.search(line))
                    if matcher is not None
                    else (
                        needle in (
                            line
                            if case_sensitive
                            else line.lower()
                        )
                    )
                )
                if not matched:
                    continue

                line_no = index + 1
                before_start = max(index - context_before, 0)
                after_end = min(index + context_after + 1, len(lines))
                before = [
                    {
                        "line": context_index + 1,
                        "text": lines[context_index][:500],
                    }
                    for context_index in range(before_start, index)
                ]
                after = [
                    {
                        "line": context_index + 1,
                        "text": lines[context_index][:500],
                    }
                    for context_index in range(index + 1, after_end)
                ]

                results.append(
                    {
                        "path": self.workspace.relative(path),
                        "line": line_no,
                        "text": line[:500],
                        "before": before,
                        "after": after,
                    }
                )
                if len(results) >= max_results:
                    truncated = True
                    break

            if truncated:
                break

        mode = "regex" if use_regex else "literal"
        return ToolResult(
            ok=True,
            summary=(
                f"Found {len(results)} {mode} match(es) for {query!r} "
                f"across {scanned_files} text file(s)."
            ),
            data={
                "query": query,
                "mode": mode,
                "glob": filename_glob,
                "exclude": excludes,
                "case_sensitive": case_sensitive,
                "context_before": context_before,
                "context_after": context_after,
                "results": results,
                "scanned_files": scanned_files,
                "skipped_files": skipped_files,
                "truncated": truncated,
            },
        )
