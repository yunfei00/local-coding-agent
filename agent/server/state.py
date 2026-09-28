from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any

from agent.server.protocol import new_id


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
    def __init__(self) -> None:
        self._threads: dict[str, ThreadRecord] = {}
        self._messages: dict[str, list[dict[str, str]]] = {}

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
        return thread

    def touch_thread(self, thread_id: str) -> None:
        thread = self._threads.get(thread_id)
        if thread:
            thread.updated_at = now_iso()

    def get_messages(self, thread_id: str) -> list[dict[str, str]]:
        return [dict(item) for item in self._messages.get(thread_id, [])]

    def append_exchange(
        self,
        thread_id: str,
        *,
        user: str,
        assistant: str,
    ) -> None:
        messages = self._messages.setdefault(thread_id, [])
        messages.append({"role": "user", "content": user})
        messages.append({"role": "assistant", "content": assistant})
        self.touch_thread(thread_id)
