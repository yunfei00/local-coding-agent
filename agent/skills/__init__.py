"""Workspace-confined, declarative skills discovery (v1.2 foundation).

Skills are instructions/data, not executable Python plugins. Execution must go
through the existing ToolRegistry and permission policy.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import json
import re

_NAME = re.compile(r"^[a-z][a-z0-9_-]{0,63}$")
_MAX_MANIFEST = 65536
_MAX_INSTRUCTIONS = 262144


@dataclass(frozen=True)
class Skill:
    name: str
    description: str
    instructions: str
    directory: Path


def discover_skills(workspace: str | Path) -> list[Skill]:
    root = Path(workspace).resolve()
    skills_root = root / ".agent" / "skills"
    if not skills_root.is_dir() or skills_root.is_symlink():
        return []
    result: list[Skill] = []
    for directory in sorted(skills_root.iterdir()):
        if not directory.is_dir() or directory.is_symlink() or not _NAME.fullmatch(directory.name):
            continue
        manifest = directory / "skill.json"
        instructions = directory / "SKILL.md"
        if any(p.is_symlink() or not p.is_file() for p in (manifest, instructions)):
            continue
        if any(not p.resolve().is_relative_to(root) for p in (manifest, instructions)):
            continue
        if manifest.stat().st_size > _MAX_MANIFEST or instructions.stat().st_size > _MAX_INSTRUCTIONS:
            continue
        try:
            info = json.loads(manifest.read_text(encoding="utf-8"))
            name = info["name"]
            description = info["description"]
            if name != directory.name or not isinstance(description, str) or len(description) > 1000:
                continue
            result.append(Skill(name, description, instructions.read_text(encoding="utf-8"), directory))
        except (OSError, UnicodeError, ValueError, KeyError, TypeError):
            continue
    return result
