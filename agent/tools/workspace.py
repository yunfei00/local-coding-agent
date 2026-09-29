from __future__ import annotations

import os
from pathlib import Path

from agent.tools.base import ToolError


DEFAULT_IGNORED_DIRS = {
    ".git",
    ".venv",
    "node_modules",
    "dist",
    "dist-electron",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
}


class Workspace:
    def __init__(self, root: str | Path) -> None:
        root_path = Path(root).expanduser().resolve(strict=True)
        if not root_path.is_dir():
            raise ToolError("WORKSPACE_NOT_DIRECTORY", "Workspace must be a directory.")
        self.root = root_path

    @property
    def display_path(self) -> str:
        return str(self.root)

    def resolve(
        self,
        value: str | Path = ".",
        *,
        must_exist: bool = False,
    ) -> Path:
        raw = Path(value)
        candidate = raw if raw.is_absolute() else self.root / raw
        resolved = candidate.expanduser().resolve(strict=must_exist)

        try:
            common = os.path.commonpath(
                [
                    os.path.normcase(str(self.root)),
                    os.path.normcase(str(resolved)),
                ]
            )
        except ValueError as exc:
            raise ToolError(
                "PATH_OUTSIDE_WORKSPACE",
                f"Path is outside the workspace: {value}",
            ) from exc

        if os.path.normcase(common) != os.path.normcase(str(self.root)):
            raise ToolError(
                "PATH_OUTSIDE_WORKSPACE",
                f"Path is outside the workspace: {value}",
            )

        return resolved

    def relative(self, path: str | Path) -> str:
        resolved = self.resolve(path, must_exist=False)
        return str(resolved.relative_to(self.root)).replace("\\", "/")
