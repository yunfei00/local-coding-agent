"""Bounded, non-sensitive execution counters for Phase 27."""
from __future__ import annotations

from dataclasses import dataclass, field
from time import perf_counter
from typing import Any


@dataclass
class TurnMetrics:
    started: float = field(default_factory=perf_counter)
    model_steps: int = 0
    tool_calls: int = 0
    tool_failures: int = 0
    retries: int = 0
    tool_duration_ms: int = 0
    context: dict[str, Any] = field(default_factory=dict)

    def record_context(self, usage: dict[str, Any]) -> None:
        self.context = {"estimated_input_tokens": int(usage.get("estimated_input_tokens", 0)),
                        "context_sources": {str(k): max(0, int(v)) for k, v in
                                            usage.get("context_sources", {}).items()}}

    def record_tool(self, duration_ms: int, *, ok: bool) -> None:
        self.tool_calls += 1
        self.tool_duration_ms += max(0, int(duration_ms))
        if not ok:
            self.tool_failures += 1

    def summary(self) -> dict[str, Any]:
        return {
            "elapsed_ms": max(0, round((perf_counter() - self.started) * 1000)),
            "model_steps": self.model_steps,
            "tool_calls": self.tool_calls,
            "tool_failures": self.tool_failures,
            "provider_retries": self.retries,
            "tool_duration_ms": self.tool_duration_ms,
            "context_token_estimate": self.context.get("estimated_input_tokens", 0),
            "context_sources": self.context.get("context_sources", {}),
        }
