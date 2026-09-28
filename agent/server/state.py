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
    created_at: str
    updated_at: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class InMemoryState:
    def __init__(self) -> None:
        self._threads: dict[str, ThreadRecord] = {}

    def create_thread(self, title: str | None = None) -> ThreadRecord:
        timestamp = now_iso()
        thread = ThreadRecord(
            id=new_id("thread"),
            title=(title or "New thread").strip() or "New thread",
            created_at=timestamp,
            updated_at=timestamp,
        )
        self._threads[thread.id] = thread
        return thread

    def list_threads(self) -> list[ThreadRecord]:
        return sorted(
            self._threads.values(),
            key=lambda item: item.updated_at,
            reverse=True,
        )

    def get_thread(self, thread_id: str) -> ThreadRecord | None:
        return self._threads.get(thread_id)

    def touch_thread(self, thread_id: str) -> None:
        thread = self._threads.get(thread_id)
        if thread:
            thread.updated_at = now_iso()
