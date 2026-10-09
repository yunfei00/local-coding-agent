from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import os
from pathlib import Path
from typing import Any

from agent.core.project_detection import ProjectDetection, detect_project
from agent.core.repository_map import RepositoryMap
from agent.persistence.store import SQLiteStore
from agent.server.protocol import new_id
from agent.server.state import InMemoryState, ThreadRecord
from agent.tools.registry import ToolRegistry
from agent.tools.workspace import Workspace


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

    def ensure_thread(self, *, active_model: str | None) -> ThreadRecord:
        thread = self.active_thread()
        if thread:
            return thread

        existing = self.state.list_threads()
        if existing:
            self.active_thread_id = existing[0].id
            self.persist()
            return existing[0]

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
                repository_map=RepositoryMap(workspace.root),
            )
            project.repository_map.build()
            self._projects[project.id] = project
            self._path_index[os.path.normcase(project.path)] = project.id

        saved_active = self.store.get_setting("active_project_id")
        if saved_active and saved_active in self._projects:
            self.active_project_id = saved_active
        elif self._projects:
            self.active_project_id = self.list_projects()[0].id

    def _set_active(self, project_id: str) -> None:
        self.active_project_id = project_id
        if self.store:
            self.store.set_setting("active_project_id", project_id)

    @property
    def active(self) -> ProjectSession | None:
        if not self.active_project_id:
            return None
        return self._projects.get(self.active_project_id)

    def open(
        self,
        path: str | Path,
        *,
        active_model: str | None,
    ) -> tuple[ProjectSession, ThreadRecord, bool]:
        workspace = Workspace(path)
        key = os.path.normcase(str(workspace.root))
        existing_id = self._path_index.get(key)

        created = False
        if existing_id:
            project = self._projects[existing_id]
            project.touch()
        else:
            timestamp = now_iso()
            project_id = new_id("project")
            state = InMemoryState(
                store=self.store,
                project_id=project_id,
            )
            project = ProjectSession(
                id=project_id,
                workspace=workspace,
                tools=ToolRegistry(workspace),
                state=state,
                created_at=timestamp,
                updated_at=timestamp,
                store=self.store,
                repository_map=RepositoryMap(workspace.root),
            )
            project.repository_map.build()
            project.persist()
            self._projects[project.id] = project
            self._path_index[key] = project.id
            created = True

        self._set_active(project.id)
        thread = project.ensure_thread(active_model=active_model)
        return project, thread, created

    def select(
        self,
        project_id: str,
        *,
        active_model: str | None,
    ) -> tuple[ProjectSession, ThreadRecord] | None:
        project = self._projects.get(project_id)
        if not project:
            return None
        self._set_active(project.id)
        project.touch()
        thread = project.ensure_thread(active_model=active_model)
        return project, thread

    def list_projects(self) -> list[ProjectSession]:
        return sorted(
            self._projects.values(),
            key=lambda project: project.updated_at,
            reverse=True,
        )

    def get(self, project_id: str) -> ProjectSession | None:
        return self._projects.get(project_id)

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
            result.append(data)
        return result
