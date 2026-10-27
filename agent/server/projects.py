from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import os
import re
from pathlib import Path
from typing import Any

from agent.core.project_detection import ProjectDetection, detect_project
from agent.core.repository_map import RepositoryMap
from agent.persistence.store import SQLiteStore
from agent.server.protocol import new_id
from agent.server.state import InMemoryState, ThreadRecord
from agent.tools.registry import ToolRegistry
from agent.tools.workspace import Workspace
from agent.tools.base import ToolError


def create_project_folder(parent_path: str, name: str) -> Path:
    """Create one new directory only; never reuse/overwrite an existing workspace."""
    if not isinstance(name, str) or not 1 <= len(name) <= 100 or name != name.strip() or name.endswith("."):
        raise ToolError("INVALID_PROJECT_NAME", "Use a project name of 1–100 characters without leading/trailing spaces or dots.")
    if name in {".", ".."} or re.search(r'[<>:"/\\|?*\x00-\x1f]', name) or re.fullmatch(r"(?:CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\..*)?", name, re.I):
        raise ToolError("INVALID_PROJECT_NAME", "Project name contains a reserved name or invalid path characters.")
    if not isinstance(parent_path, str) or not parent_path.strip() or not Path(parent_path).is_absolute():
        raise ToolError("INVALID_PROJECT_LOCATION", "Choose an existing absolute parent folder.")
    parent = Path(parent_path).resolve(strict=True)
    if not parent.is_dir():
        raise ToolError("INVALID_PROJECT_LOCATION", "Project location must be an existing directory.")
    target = parent / name
    try:
        target.mkdir()  # Exclusive, nonrecursive; rejects files, directories and symlinks.
    except FileExistsError as exc:
        raise ToolError("PROJECT_EXISTS", "That folder already exists. Choose another name or use Projects + → Add existing folder.") from exc
    return target


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class ProjectSession:
    id: str
    workspace: Workspace
    tools: ToolRegistry
    state: InMemoryState
    created_at: str
    updated_at: str
    active_thread_id: str | None = None
    store: SQLiteStore | None = None
    repository_map: RepositoryMap | None = None

    @property
    def name(self) -> str:
        return self.workspace.root.name

    @property
    def path(self) -> str:
        return self.workspace.display_path

    def detection(self) -> ProjectDetection:
        return detect_project(self.workspace.root)

    def ensure_repository_map(self) -> RepositoryMap:
        if self.repository_map is None:
            self.repository_map = RepositoryMap(self.workspace.root)
            self.repository_map.build()
        return self.repository_map

    def refresh_repository_paths(self, paths: list[str] | tuple[str, ...]) -> None:
        self.ensure_repository_map().refresh_paths(paths)

    def persist(self) -> None:
        if not self.store:
            return
        self.store.save_project(
            project_id=self.id,
            path=self.path,
            created_at=self.created_at,
            updated_at=self.updated_at,
            active_thread_id=self.active_thread_id,
        )

    def touch(self) -> None:
        self.updated_at = now_iso()
        self.persist()

    def active_thread(self) -> ThreadRecord | None:
        if not self.active_thread_id:
            return None
        return self.state.get_thread(self.active_thread_id)

    def ensure_thread(self, *, active_model: str | None, create: bool = True) -> ThreadRecord | None:
        thread = self.active_thread()
        if thread:
            return thread

        existing = self.state.list_threads()
        if existing:
            self.active_thread_id = existing[0].id
            self.persist()
            return existing[0]

        if not create:
            self.active_thread_id = None
            self.persist()
            return None
        thread = self.state.create_thread(active_model=active_model)
        self.active_thread_id = thread.id
        self.touch()
        return thread

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "path": self.path,
            "tools": self.tools.names,
            "detection": self.detection().to_dict(),
            "repository_map": self.ensure_repository_map().payload(),
            "thread_count": len(self.state.list_threads()),
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "active": False,
        }


class ProjectRegistry:
    def __init__(self, store: SQLiteStore | None = None) -> None:
        self.store = store
        self._projects: dict[str, ProjectSession] = {}
        self._path_index: dict[str, str] = {}
        self._removed: set[str] = set()
        self.active_project_id: str | None = None
        self._hydrate()

    def _hydrate(self) -> None:
        if not self.store:
            return

        for row in self.store.list_projects():
            try:
                workspace = Workspace(str(row["path"]))
            except (OSError, Exception):
                continue

            project_id = str(row["id"])
            if self.store.get_setting("project.hidden:" + project_id) == "1":
                self._removed.add(project_id)
            state = InMemoryState(
                store=self.store,
                project_id=project_id,
            )
            state.load_from_store()

            project = ProjectSession(
                id=project_id,
                workspace=workspace,
                tools=ToolRegistry(workspace),
                state=state,
                created_at=str(row["created_at"]),
                updated_at=str(row["updated_at"]),
                active_thread_id=(
                    str(row["active_thread_id"])
                    if row.get("active_thread_id") is not None
                    else None
                ),
                store=self.store,
                repository_map=RepositoryMap(workspace.root) if project_id not in self._removed else None,
            )
            if project_id not in self._removed:
                project.repository_map.build()
            self._projects[project.id] = project
            self._path_index[os.path.normcase(project.path)] = project.id

        saved_active = self.store.get_setting("active_project_id")
        if saved_active and self.get(saved_active):
            self.active_project_id = saved_active
        elif visible := self.list_projects():
            self._set_active(visible[0].id)
        elif saved_active:
            self._set_active(None)

    def _set_active(self, project_id: str | None) -> None:
        self.active_project_id = project_id
        if self.store:
            self.store.set_setting("active_project_id", project_id or "")

    @property
    def active(self) -> ProjectSession | None:
        if not self.active_project_id:
            return None
        return self.get(self.active_project_id)

    def open(
        self,
        path: str | Path,
        *,
        active_model: str | None,
        defer_thread: bool = False,
    ) -> tuple[ProjectSession, ThreadRecord | None, bool]:
        workspace = Workspace(path)
        key = os.path.normcase(workspace.display_path)
        existing_id = self._path_index.get(key)

        created = False
        if existing_id:
            project = self._projects[existing_id]
            if existing_id in self._removed:
                if self.store:
                    self.store.set_setting("project.hidden:" + existing_id, "")
                self._removed.discard(existing_id)
            project.touch()
        else:
            # A path may have been unavailable during startup hydration (for
            # example an offline company drive). Reuse its durable identity.
            saved = next((row for row in self.store.list_projects() if os.path.normcase(str(row["path"])) == key), None) if self.store else None
            timestamp = now_iso()
            project_id = str(saved["id"]) if saved else new_id("project")
            state = InMemoryState(
                store=self.store,
                project_id=project_id,
            )
            if saved:
                state.load_from_store()
            project = ProjectSession(
                id=project_id,
                workspace=workspace,
                tools=ToolRegistry(workspace),
                state=state,
                created_at=str(saved["created_at"]) if saved else timestamp,
                updated_at=timestamp,
                active_thread_id=saved.get("active_thread_id") if saved else None,
                store=self.store,
                repository_map=RepositoryMap(workspace.root),
            )
            project.repository_map.build()
            project.persist()
            if saved and self.store:
                self.store.set_setting("project.hidden:" + project_id, "")
                self._removed.discard(project_id)
            self._projects[project.id] = project
            self._path_index[key] = project.id
            created = saved is None

        self._set_active(project.id)
        thread = project.ensure_thread(active_model=active_model, create=not defer_thread)
        return project, thread, created

    def select(
        self,
        project_id: str,
        *,
        active_model: str | None,
        defer_thread: bool = False,
    ) -> tuple[ProjectSession, ThreadRecord | None] | None:
        project = self.get(project_id)
        if not project:
            return None
        self._set_active(project.id)
        project.touch()
        thread = project.ensure_thread(active_model=active_model, create=not defer_thread)
        return project, thread

    def list_projects(self) -> list[ProjectSession]:
        return sorted(
            (project for project in self._projects.values() if project.id not in self._removed),
            key=lambda project: project.updated_at,
            reverse=True,
        )

    def get(self, project_id: str) -> ProjectSession | None:
        return None if project_id in self._removed else self._projects.get(project_id)

    def is_removed(self, project_id: str) -> bool:
        return project_id in self._removed and project_id in self._projects

    def remove(self, project_id: str) -> bool:
        """Hide registration only. Keep files, threads, worktrees and task audit."""
        if project_id not in self._projects:
            return False
        visible = [project for project in self.list_projects() if project.id != project_id]
        active_id = (visible[0].id if visible else None) if self.active_project_id == project_id else self.active_project_id
        if self.store:
            # Save visibility and fallback together, before changing memory.
            with self.store.connection:
                self.store.connection.executemany("INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                    [("project.hidden:" + project_id, "1"), ("active_project_id", active_id or "")])
        self._removed.add(project_id)
        self._projects[project_id].repository_map = None
        self.active_project_id = active_id
        return True

    def mark_active_thread(self, thread_id: str) -> None:
        project = self.active
        if project and project.state.get_thread(thread_id):
            project.active_thread_id = thread_id
            project.touch()

    def project_payload(self, project: ProjectSession) -> dict[str, Any]:
        project_data = project.to_dict()
        project_data["active"] = project.id == self.active_project_id
        active_thread = project.active_thread()
        return {
            "project": project_data,
            "threads": [item.to_dict() for item in project.state.list_threads()],
            "active_thread": active_thread.to_dict() if active_thread else None,
            "messages": (
                project.state.get_messages(active_thread.id)
                if active_thread
                else []
            ),
        }

    def list_payload(self) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        for project in self.list_projects():
            data = project.to_dict()
            data["active"] = project.id == self.active_project_id
            data["threads"] = [thread.to_dict() for thread in project.state.list_threads()]
            result.append(data)
        return result
