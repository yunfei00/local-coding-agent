"""Agent Skills discovery: standard SKILL.md frontmatter and legacy skill.json."""
from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
import json
import re

_NAME = re.compile(r"^[a-z][a-z0-9-]{0,63}$")
_MAX_MANIFEST = 65536
_MAX_INSTRUCTIONS = 262144

@dataclass(frozen=True)
class Skill:
    name: str
    description: str
    instructions: str
    directory: Path

def _frontmatter(content: str) -> dict[str, str]:
    if not content.startswith("---\n"):
        return {}
    end = content.find("\n---", 4)
    if end < 0:
        return {}
    result = {}
    for line in content[4:end].splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        key, value = key.strip(), value.strip()
        if key in {"name", "description"}:
            result[key] = value.strip("'\"")
    return result

def _discover_root(skills_root: Path) -> list[Skill]:
    if not skills_root.is_dir() or skills_root.is_symlink():
        return []
    result = []
    for directory in sorted(skills_root.iterdir()):
        if not directory.is_dir() or directory.is_symlink() or not _NAME.fullmatch(directory.name):
            continue
        instructions = directory / "SKILL.md"
        if instructions.is_symlink() or not instructions.is_file() or instructions.stat().st_size > _MAX_INSTRUCTIONS:
            continue
        manifest = directory / "skill.json"
        if manifest.exists() and (manifest.is_symlink() or not manifest.is_file() or manifest.stat().st_size > _MAX_MANIFEST):
            continue
        try:
            content = instructions.read_text(encoding="utf-8")
            info = _frontmatter(content)
            if not info and manifest.is_file():
                info = json.loads(manifest.read_text(encoding="utf-8"))
            name, description = info["name"], info["description"]
            if name != directory.name or not _NAME.fullmatch(name) or not isinstance(description, str) or not description.strip() or len(description) > 1024:
                continue
            result.append(Skill(name, description, content, directory))
        except (OSError, UnicodeError, ValueError, KeyError, TypeError):
            continue
    return result

def discover_skills(workspace: str | Path) -> list[Skill]:
    """Discover project-local .agent/skills and standard .agents/skills locations."""
    root = Path(workspace).resolve()
    result = {s.name: s for s in _discover_root(root / ".agent" / "skills")}
    for skill in _discover_root(root / ".agents" / "skills"):
        result[skill.name] = skill
    return sorted(result.values(), key=lambda s: s.name)
