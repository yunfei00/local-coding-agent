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
        self.allow_outside = False

    @property
    def display_path(self) -> str:
        return str(self.root)

    def set_full_access(self, enabled: bool) -> None:
        self.allow_outside = bool(enabled)

    def contains(self, value: str | Path) -> bool:
        raw = Path(value)
        candidate = raw if raw.is_absolute() else self.root / raw
        resolved = candidate.expanduser().resolve(strict=False)

        try:
            common = os.path.commonpath(
                [
                    os.path.normcase(str(self.root)),
                    os.path.normcase(str(resolved)),
                ]
            )
        except ValueError:
            return False

        return os.path.normcase(common) == os.path.normcase(str(self.root))

    def resolve(
        self,
        value: str | Path = ".",
        *,
        must_exist: bool = False,
    ) -> Path:
        raw = Path(value)
        candidate = raw if raw.is_absolute() else self.root / raw
        resolved = candidate.expanduser().resolve(strict=must_exist)

        if not self.allow_outside and not self.contains(resolved):
            raise ToolError(
                "PATH_OUTSIDE_WORKSPACE",
                f"Path is outside the workspace: {value}",
            )

        return resolved

    def relative(self, path: str | Path) -> str:
        resolved = self.resolve(path, must_exist=False)
        if self.contains(resolved):
            return str(resolved.relative_to(self.root)).replace("\\", "/")
        return str(resolved)

    def display(self, path: str | Path) -> str:
        return self.relative(path)
