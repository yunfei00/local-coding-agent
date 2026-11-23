"""Skill manager with standard manifests and safe local package installation."""
from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
import json
import shutil
import tempfile
import zipfile
import hashlib
from agent.skills import Skill, discover_skills, _discover_root, _NAME, _frontmatter

MAX_TOTAL = 16 * 1024 * 1024
MAX_FILES = 256

@dataclass(frozen=True)
class SkillInfo:
    name: str
    description: str
    source: str
    enabled: bool

class SkillManager:
    def __init__(self, workspace: str | Path, *, builtin: str | Path | None = None, user: str | Path | None = None):
        self.workspace = Path(workspace).resolve()
        self.roots = []
        if builtin:
            self.roots.append(("builtin", Path(builtin).resolve()))
        if user:
            self.roots.append(("user", Path(user).resolve()))
        self.roots.append(("project", self.workspace))
        self.disabled_file = self.workspace / ".agent" / "disabled-skills.json"

    def _scan(self, root: Path) -> list[Skill]:
        return discover_skills(root) + _discover_root(root / "skills")

    def _disabled(self) -> set[str]:
        try:
            raw = json.loads(self.disabled_file.read_text(encoding="utf-8"))
            return set(raw) if isinstance(raw, list) else set()
        except (OSError, ValueError):
            return set()

    def catalog(self) -> list[SkillInfo]:
        selected = {}
        disabled = self._disabled()
        for source, root in self.roots:
            for skill in self._scan(root):
                selected[skill.name] = SkillInfo(skill.name, skill.description, source, skill.name not in disabled)
        return sorted(selected.values(), key=lambda x: x.name)

    def resolve(self, name: str) -> Skill | None:
        if name in self._disabled():
            return None
        for _, root in reversed(self.roots):
            for skill in self._scan(root):
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

    def _install_directory(self, source: Path) -> str:
        if source.is_symlink() or not source.is_dir():
            raise ValueError("Invalid skill source")
        # Local source folder names need not match declared skill names.
        instructions_file = source / "SKILL.md"
        if not instructions_file.is_file() or instructions_file.is_symlink() or instructions_file.stat().st_size > 262144:
            raise ValueError("Invalid SKILL.md")
        instructions = instructions_file.read_text(encoding="utf-8")
        info = _frontmatter(instructions)
        if not info:
            manifest = source / "skill.json"
            if not manifest.is_file() or manifest.is_symlink() or manifest.stat().st_size > 65536:
                raise ValueError("Missing skill metadata")
            info = json.loads(manifest.read_text(encoding="utf-8"))
        name = info.get("name")
        description = info.get("description")
        if not isinstance(name, str) or not _NAME.fullmatch(name) or not isinstance(description, str) or not description.strip():
            raise ValueError("Invalid skill metadata")
        target = self.workspace / ".agent" / "skills" / name
        if target.exists():
            raise FileExistsError(name)
        files = [p for p in source.rglob("*")]
        if len(files) > MAX_FILES or sum(p.stat().st_size for p in files if p.is_file()) > MAX_TOTAL:
            raise ValueError("Skill package too large")
        for p in files:
            if p.is_symlink() or not p.resolve().is_relative_to(source.resolve()):
                raise ValueError("Symlinks and path escapes are forbidden")
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(source, target, symlinks=False)
        return name

    def install_local(self, source: str | Path) -> str:
        source = Path(source).expanduser()
        if source.is_symlink():
            raise ValueError("Symlink skill sources are forbidden")
        source = source.resolve(strict=True)
        if source.is_dir():
            return self._install_directory(source)
        if source.suffix.lower() != ".zip":
            raise ValueError("Only skill directories and ZIP files are supported")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with zipfile.ZipFile(source) as archive:
                infos = archive.infolist()
                if len(infos) > MAX_FILES or sum(x.file_size for x in infos) > MAX_TOTAL:
                    raise ValueError("ZIP too large")
                for info in infos:
                    p = Path(info.filename.replace("\\", "/"))
                    if p.is_absolute() or ".." in p.parts or not p.parts or (info.external_attr >> 16) & 0o170000 == 0o120000:
                        raise ValueError("Unsafe ZIP entry")
                    if not (root / p).resolve().is_relative_to(root.resolve()):
                        raise ValueError("ZIP path escape")
                archive.extractall(root)
            candidates = [p for p in root.rglob("SKILL.md") if p.parent != root]
            if len(candidates) != 1:
                raise ValueError("ZIP must contain exactly one skill")
            return self._install_directory(candidates[0].parent)

    def _project_skill(self, name: str) -> Path:
        if not isinstance(name, str) or not _NAME.fullmatch(name):
            raise ValueError("Invalid skill name")
        return self.workspace / ".agent" / "skills" / name

    def backup_project(self, name: str) -> str:
        """Snapshot an installed skill before replacement; never run its scripts."""
        source = self._project_skill(name)
        if not source.is_dir() or source.is_symlink():
            raise ValueError("Project skill not installed")
        for item in source.rglob("*"):
            if item.is_symlink():
                raise ValueError("Unsafe symlink")
        backup_root = self.workspace / ".agent" / "skills-backups" / name
        backup_root.mkdir(parents=True, exist_ok=True)
        digest = self.inventory_hash(name)
        target = backup_root / digest
        if not target.exists():
            shutil.copytree(source, target)
        return digest

    def rollback_project(self, name: str, revision: str) -> None:
        """Restore an explicit local snapshot with an atomic directory swap."""
        source = self._project_skill(name)
        if not isinstance(revision, str) or len(revision) != 64 or any(c not in "0123456789abcdef" for c in revision):
            raise ValueError("Invalid revision")
        snapshot = self.workspace / ".agent" / "skills-backups" / name / revision
        if not snapshot.is_dir() or snapshot.is_symlink():
            raise ValueError("Backup not found")
        for item in snapshot.rglob("*"):
            if item.is_symlink():
                raise ValueError("Unsafe backup")
        staging = source.with_name(source.name + ".restore-staging")
        if staging.exists():
            raise ValueError("Restore already in progress")
        shutil.copytree(snapshot, staging)
        old = source.with_name(source.name + ".restore-old")
        try:
            if old.exists():
                raise ValueError("Previous restore not cleaned")
            if source.exists():
                source.rename(old)
            try:
                staging.rename(source)
            except Exception:
                if old.exists():
                    old.rename(source)
                raise
            if old.exists():
                shutil.rmtree(old)
        finally:
            if staging.exists():
                shutil.rmtree(staging)

    def list_backups(self, name: str) -> list[str]:
        self._project_skill(name)
        folder = self.workspace / ".agent" / "skills-backups" / name
        if not folder.is_dir():
            return []
        return sorted(p.name for p in folder.iterdir() if p.is_dir() and len(p.name) == 64)

    def update_local(self, name: str, new_source: str | Path) -> str:
        """Replace a project skill, preserving a rollback snapshot on failure."""
        source = self._project_skill(name)
        if not source.is_dir() or source.is_symlink():
            raise ValueError("Project skill not installed")
        new_source_path = Path(new_source).resolve(strict=True)
        if new_source_path == source or source in new_source_path.parents:
            raise ValueError("Cannot update a skill from itself")
        revision = self.backup_project(name)
        old = source.with_name(source.name + ".update-old")
        if old.exists():
            raise ValueError("Previous update not cleaned")
        source.rename(old)
        try:
            installed = self.install_local(new_source)
            if installed != name:
                raise ValueError("Updated skill name differs")
        except Exception:
            if source.exists():
                shutil.rmtree(source)
            old.rename(source)
            raise
        shutil.rmtree(old)
        return revision

    def uninstall_project(self, name: str) -> None:
        if not _NAME.fullmatch(name):
            raise ValueError("Invalid skill name")
        target = self.workspace / ".agent" / "skills" / name
        if not target.is_dir() or target.is_symlink():
            raise ValueError("Project skill not installed")
        shutil.rmtree(target)

    def instructions(self, name: str) -> str:
        skill = self.resolve(name)
        if skill is None:
            raise ValueError("Skill not available")
        return skill.instructions

    def inventory_hash(self, name: str) -> str:
        skill = self.resolve(name)
        if skill is None:
            raise ValueError("Skill not available")
        digest = hashlib.sha256()
        for file in sorted(p for p in skill.directory.rglob("*") if p.is_file()):
            if file.is_symlink():
                raise ValueError("Unsafe skill")
            digest.update(file.relative_to(skill.directory).as_posix().encode())
            digest.update(file.read_bytes())
        return digest.hexdigest()
