"""Bounded, non-sensitive execution counters for Phase 27."""
from __future__ import annotations

from dataclasses import dataclass, field
from time import perf_counter


@dataclass
class TurnMetrics:
    started: float = field(default_factory=perf_counter)
    model_steps: int = 0
    tool_calls: int = 0
    tool_failures: int = 0
    retries: int = 0
    tool_duration_ms: int = 0

    def record_tool(self, duration_ms: int, *, ok: bool) -> None:
        self.tool_calls += 1
        self.tool_duration_ms += max(0, int(duration_ms))
        if not ok:
            self.tool_failures += 1

    def summary(self) -> dict[str, int]:
        return {
            "elapsed_ms": max(0, round((perf_counter() - self.started) * 1000)),
            "model_steps": self.model_steps,
            "tool_calls": self.tool_calls,
            "tool_failures": self.tool_failures,
            "provider_retries": self.retries,
            "tool_duration_ms": self.tool_duration_ms,
        }
