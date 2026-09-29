from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from agent.server.protocol import new_id

if TYPE_CHECKING:
    from agent.persistence.store import SQLiteStore


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class ThreadRecord:
    id: str
    title: str
    active_model: str | None
    created_at: str
    updated_at: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class InMemoryState:
    def __init__(
        self,
        *,
        store: SQLiteStore | None = None,
        project_id: str | None = None,
    ) -> None:
        self._threads: dict[str, ThreadRecord] = {}
        self._messages: dict[str, list[dict[str, str]]] = {}
        self.store = store
        self.project_id = project_id

    def load_from_store(self) -> None:
        if not self.store or not self.project_id:
            return

        self._threads.clear()
        self._messages.clear()

        for row in self.store.list_threads(self.project_id):
            thread = ThreadRecord(
                id=str(row["id"]),
                title=str(row["title"]),
                active_model=(
                    str(row["active_model"])
                    if row.get("active_model") is not None
                    else None
                ),
                created_at=str(row["created_at"]),
                updated_at=str(row["updated_at"]),
            )
            self._threads[thread.id] = thread
            self._messages[thread.id] = self.store.list_messages(thread.id)

    def _persist_thread(self, thread: ThreadRecord) -> None:
        if not self.store or not self.project_id:
            return
        self.store.save_thread(
            thread_id=thread.id,
            project_id=self.project_id,
            title=thread.title,
            active_model=thread.active_model,
            created_at=thread.created_at,
            updated_at=thread.updated_at,
        )

    def create_thread(
        self,
        title: str | None = None,
        *,
        active_model: str | None = None,
    ) -> ThreadRecord:
        timestamp = now_iso()
        thread = ThreadRecord(
            id=new_id("thread"),
            title=(title or "New thread").strip() or "New thread",
            active_model=active_model,
            created_at=timestamp,
            updated_at=timestamp,
        )
        self._threads[thread.id] = thread
        self._messages[thread.id] = []
        self._persist_thread(thread)
        return thread

    def list_threads(self) -> list[ThreadRecord]:
        return sorted(
            self._threads.values(),
            key=lambda item: item.updated_at,
            reverse=True,
        )

    def get_thread(self, thread_id: str) -> ThreadRecord | None:
        return self._threads.get(thread_id)

    def set_thread_model(self, thread_id: str, model: str) -> ThreadRecord | None:
        thread = self._threads.get(thread_id)
        if not thread:
            return None
        thread.active_model = model
        thread.updated_at = now_iso()
        self._persist_thread(thread)
        return thread

    def touch_thread(self, thread_id: str) -> None:
        thread = self._threads.get(thread_id)
        if thread:
            thread.updated_at = now_iso()
            self._persist_thread(thread)

    def get_messages(self, thread_id: str) -> list[dict[str, str]]:
        return [dict(item) for item in self._messages.get(thread_id, [])]

    def append_exchange(
        self,
        thread_id: str,
        *,
        user: str,
        assistant: str,
    ) -> None:
        timestamp = now_iso()
        messages = self._messages.setdefault(thread_id, [])
        messages.append({"role": "user", "content": user})
        messages.append({"role": "assistant", "content": assistant})

        if self.store:
            self.store.append_message(
                thread_id=thread_id,
                role="user",
                content=user,
                created_at=timestamp,
            )
            self.store.append_message(
                thread_id=thread_id,
                role="assistant",
                content=assistant,
                created_at=timestamp,
            )

        self.touch_thread(thread_id)
