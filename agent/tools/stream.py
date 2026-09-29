from __future__ import annotations

from dataclasses import dataclass
from typing import Any


DEFAULT_LIVE_OUTPUT_CHAR_LIMIT = 120_000


@dataclass
class ToolStreamState:
    max_live_chars: int = DEFAULT_LIVE_OUTPUT_CHAR_LIMIT
    sequence: int = 0
    live_chars: int = 0
    total_chars: int = 0
    truncated: bool = False

    def meta(self, event: str, **payload: Any) -> dict[str, Any]:
        return self._event(
            {
                "stream": "meta",
                "event": event,
                **payload,
            }
        )

    def output(self, stream: str, text: str) -> list[dict[str, Any]]:
        value = str(text)
        self.total_chars += len(value)
        if not value:
            return []

        events: list[dict[str, Any]] = []
        remaining = max(self.max_live_chars - self.live_chars, 0)
        if remaining > 0:
            visible = value[:remaining]
            if visible:
                self.live_chars += len(visible)
                events.append(
                    self._event(
                        {
                            "stream": stream,
                            "text": visible,
                            "live_chars": self.live_chars,
                            "total_chars": self.total_chars,
                        }
                    )
                )

        if len(value) > remaining and not self.truncated:
            self.truncated = True
            events.append(
                self.meta(
                    "stream_truncated",
                    live_char_limit=self.max_live_chars,
                    total_chars=self.total_chars,
                )
            )

        return events

    def snapshot(self) -> dict[str, Any]:
        return {
            "sequence": self.sequence,
            "live_chars": self.live_chars,
            "total_chars": self.total_chars,
            "truncated": self.truncated,
            "live_char_limit": self.max_live_chars,
        }

    def _event(self, payload: dict[str, Any]) -> dict[str, Any]:
        self.sequence += 1
        return {
            **payload,
            "sequence": self.sequence,
        }
