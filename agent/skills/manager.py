"""Local-only skill catalog with explicit trust boundaries."""
from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
import json
import shutil
from agent.skills import Skill, discover_skills

@dataclass(frozen=True)
class SkillInfo:
    name: str
    description: str
    source: str
    enabled: bool

class SkillManager:
    def __init__(self, workspace: str | Path, *, builtin: str | Path | None = None, user: str | Path | None = None):
        self.workspace = Path(workspace).resolve()
        self.roots = [("builtin", Path(builtin).resolve())] if builtin else []
        if user:
            self.roots.append(("user", Path(user).resolve()))
        self.roots.append(("project", self.workspace))
        self.disabled_file = self.workspace / ".agent" / "disabled-skills.json"

    def _disabled(self) -> set[str]:
        try:
            raw = json.loads(self.disabled_file.read_text(encoding="utf-8"))
            return set(raw) if isinstance(raw, list) else set()
        except (OSError, ValueError):
            return set()

    def catalog(self) -> list[SkillInfo]:
        selected: dict[str, SkillInfo] = {}
        disabled = self._disabled()
        for source, root in self.roots:
            for skill in discover_skills(root):
                selected[skill.name] = SkillInfo(skill.name, skill.description, source, skill.name not in disabled)
        return sorted(selected.values(), key=lambda x: x.name)

    def resolve(self, name: str) -> Skill | None:
        if name in self._disabled():
            return None
        for _, root in reversed(self.roots):
            for skill in discover_skills(root):
                if skill.name == name:
                    return skill
        return None

    def set_enabled(self, name: str, enabled: bool) -> None:
        if not any(x.name == name for x in self.catalog()):
            raise ValueError("Unknown skill")
        disabled = self._disabled()
        disabled.discard(name) if enabled else disabled.add(name)
        self.disabled_file.parent.mkdir(parents=True, exist_ok=True)
        self.disabled_file.write_text(json.dumps(sorted(disabled)), encoding="utf-8")

    def install_local(self, source: str | Path) -> str:
        """Copy only declarative files; never install dependencies or execute hooks."""
        source = Path(source).resolve(strict=True)
        manifest = source / "skill.json"
        data = json.loads(manifest.read_text(encoding="utf-8"))
        name = data["name"]
        if not isinstance(name, str) or not name.isascii() or not name.replace("-", "").replace("_", "").isalnum() or name.startswith(("-", "_")) or len(name) > 64:
            raise ValueError("Invalid skill name")
        target = self.workspace / ".agent" / "skills" / name
        if target.exists():
            raise FileExistsError(name)
        if (source / "SKILL.md").is_symlink() or manifest.is_symlink():
            raise ValueError("Symlink not permitted")
        target.mkdir(parents=True)
        try:
            for filename in ("skill.json", "SKILL.md"):
                file = source / filename
                if not file.is_file() or file.stat().st_size > 262144:
                    raise ValueError("Missing or oversized skill file")
                shutil.copyfile(file, target / filename)
            if not any(s.name == name for s in discover_skills(self.workspace)):
                raise ValueError("Invalid skill")
        except Exception:
            shutil.rmtree(target)
            raise
        return name

    def uninstall_project(self, name: str) -> None:
        skill = next((s for s in discover_skills(self.workspace) if s.name == name), None)
        if skill is None:
            raise ValueError("Project skill not installed")
        shutil.rmtree(skill.directory)
