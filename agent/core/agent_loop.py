from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any


DEFAULT_HISTORY_CHAR_BUDGET = 48_000
DEFAULT_TOOL_PAYLOAD_CHAR_BUDGET = 24_000
MAX_FIELD_CHARS = 8_000

CODE_SUFFIXES = {
    ".py",
    ".pyi",
    ".js",
    ".jsx",
    ".ts",
    ".tsx",
    ".java",
    ".kt",
    ".kts",
    ".go",
    ".rs",
    ".c",
    ".cc",
    ".cpp",
    ".h",
    ".hpp",
    ".cs",
    ".swift",
    ".sh",
    ".ps1",
    ".bat",
    ".cmd",
    ".gradle",
}


def canonical_tool_fingerprint(name: str, arguments: dict[str, Any]) -> str:
    return name + ":" + json.dumps(
        arguments,
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
        default=str,
    )


def trim_history(
    history: list[dict[str, Any]],
    *,
    max_chars: int = DEFAULT_HISTORY_CHAR_BUDGET,
) -> list[dict[str, Any]]:
    if max_chars <= 0 or not history:
        return []

    selected: list[dict[str, Any]] = []
    used = 0

    for raw in reversed(history):
        message = dict(raw)
        content = str(message.get("content") or "")
        cost = len(content) + 32

        if selected and used + cost > max_chars:
            break

        if not selected and cost > max_chars:
            keep = max(max_chars - 64, 0)
            message["content"] = (
                "[Older content truncated]\n" + content[-keep:]
                if keep
                else ""
            )
            selected.append(message)
            break

        selected.append(message)
        used += cost

    selected.reverse()
    return selected


def _compact_value(value: Any, *, depth: int = 0) -> Any:
    if depth > 6:
        return "[nested value truncated]"

    if isinstance(value, str):
        if len(value) <= MAX_FIELD_CHARS:
            return value
        head = value[: MAX_FIELD_CHARS // 3]
        tail = value[-(MAX_FIELD_CHARS - len(head)) :]
        return head + "\n...[truncated]...\n" + tail

    if isinstance(value, dict):
        return {
            str(key): _compact_value(item, depth=depth + 1)
            for key, item in value.items()
        }

    if isinstance(value, list):
        if len(value) <= 50:
            return [_compact_value(item, depth=depth + 1) for item in value]
        head = [_compact_value(item, depth=depth + 1) for item in value[:25]]
        tail = [_compact_value(item, depth=depth + 1) for item in value[-25:]]
        return head + [{"truncated_items": len(value) - 50}] + tail

    return value


def compact_tool_payload(
    payload: dict[str, Any],
    *,
    max_chars: int = DEFAULT_TOOL_PAYLOAD_CHAR_BUDGET,
) -> dict[str, Any]:
    compacted = _compact_value(payload)
    encoded = json.dumps(
        compacted,
        ensure_ascii=False,
        separators=(",", ":"),
        default=str,
    )
    if len(encoded) <= max_chars:
        return compacted

    minimal: dict[str, Any] = {
        "ok": bool(payload.get("ok")),
        "summary": str(payload.get("summary") or ""),
        "exit_code": payload.get("exit_code"),
        "duration_ms": payload.get("duration_ms"),
        "changed_paths": list(payload.get("changed_paths") or []),
        "truncated_for_model": True,
    }

    stdout = str(payload.get("stdout") or "")
    stderr = str(payload.get("stderr") or "")
    if stdout:
        minimal["stdout_tail"] = stdout[-8_000:]
    if stderr:
        minimal["stderr_tail"] = stderr[-8_000:]

    data = payload.get("data")
    if data:
        data_text = json.dumps(data, ensure_ascii=False, default=str)
        minimal["data_excerpt"] = data_text[-6_000:]

    encoded = json.dumps(minimal, ensure_ascii=False, default=str)
    if len(encoded) > max_chars:
        minimal["stdout_tail"] = str(minimal.get("stdout_tail") or "")[-3_000:]
        minimal["stderr_tail"] = str(minimal.get("stderr_tail") or "")[-3_000:]
        minimal["data_excerpt"] = str(minimal.get("data_excerpt") or "")[-3_000:]

    return minimal


@dataclass
class ToolLoopGuard:
    max_identical_calls: int = 2
    call_counts: dict[str, int] = field(default_factory=dict)
    recent_fingerprints: list[str] = field(default_factory=list)
    changed_paths: set[str] = field(default_factory=set)
    result_sequence: int = 0
    last_change_sequence: int = -1
    last_diff_sequence: int = -1
    last_validation_sequence: int = -1
    blocked_repeats: int = 0
    blocked_cycles: int = 0
    consecutive_failures: int = 0
    max_observed_consecutive_failures: int = 0
    last_block_reason: str | None = None
    last_failure_code: str | None = None
    completion_reminder_sent: bool = False

    def register_call(
        self,
        name: str,
        arguments: dict[str, Any],
    ) -> tuple[bool, int, str]:
        fingerprint = canonical_tool_fingerprint(name, arguments)
        count = self.call_counts.get(fingerprint, 0) + 1
        self.call_counts[fingerprint] = count
        self.recent_fingerprints.append(fingerprint)
        self.recent_fingerprints = self.recent_fingerprints[-12:]
        self.last_block_reason = None

        if count > self.max_identical_calls:
            self.blocked_repeats += 1
            self.last_block_reason = "identical"
            return False, count, fingerprint

        cycle_length = self._short_cycle_length()
        if cycle_length is not None:
            self.blocked_cycles += 1
            self.last_block_reason = f"cycle:{cycle_length}"
            return False, count, fingerprint

        return True, count, fingerprint

    def _short_cycle_length(self) -> int | None:
        recent = self.recent_fingerprints
        for width in (2, 3):
            if len(recent) < width * 2:
                continue
            first = recent[-(width * 2):-width]
            second = recent[-width:]
            if first == second and len(set(second)) > 1:
                return width
        return None

    def loop_abort_reason(self, *, max_blocked_repeats: int) -> str | None:
        if self.blocked_cycles > 0:
            return "short_cycle"
        if self.blocked_repeats >= max(max_blocked_repeats, 1):
            return "repeated_call"
        return None

    def record_result(self, name: str, payload: dict[str, Any]) -> None:
        self.result_sequence += 1
        sequence = self.result_sequence
        ok = bool(payload.get("ok"))

        if ok:
            self.consecutive_failures = 0
            self.last_failure_code = None
        else:
            self.consecutive_failures += 1
            self.max_observed_consecutive_failures = max(
                self.max_observed_consecutive_failures,
                self.consecutive_failures,
            )
            error = payload.get("error")
            self.last_failure_code = (
                str(error.get("code"))
                if isinstance(error, dict) and error.get("code")
                else None
            )

        paths = payload.get("changed_paths") or []
        if isinstance(paths, list) and paths:
            for path in paths:
                self.changed_paths.add(str(path))
            self.last_change_sequence = sequence
            self.completion_reminder_sent = False

            if ok:
                self.call_counts.clear()
                self.recent_fingerprints.clear()
                self.blocked_repeats = 0
                self.blocked_cycles = 0
                self.last_block_reason = None

        if name == "git_diff" and ok:
            self.last_diff_sequence = sequence

        if (
            name == "run_command"
            and ok
            and payload.get("exit_code") in (0, None)
        ):
            self.last_validation_sequence = sequence

    def failure_limit_reached(self, *, max_consecutive_failures: int) -> bool:
        return self.consecutive_failures >= max(max_consecutive_failures, 1)

    def changed_code(self) -> bool:
        return any(
            any(path.lower().endswith(suffix) for suffix in CODE_SUFFIXES)
            for path in self.changed_paths
        )

    def completion_gaps(self) -> list[str]:
        if self.last_change_sequence < 0:
            return []

        gaps: list[str] = []
        if self.last_diff_sequence < self.last_change_sequence:
            gaps.append("git_diff")
        if (
            self.changed_code()
            and self.last_validation_sequence < self.last_change_sequence
        ):
            gaps.append("validation")
        return gaps

    def completion_note(self) -> str | None:
        gaps = self.completion_gaps()
        if not gaps:
            return None

        parts = [
            "Before finishing, complete the verification for the changes you made."
        ]
        if "git_diff" in gaps:
            parts.append("Inspect the current Git diff after the latest file change.")
        if "validation" in gaps:
            parts.append(
                "Run an appropriate existing test/build/check command after the latest code change. "
                "If no safe validation command can be identified, state that explicitly instead of claiming verification."
            )
        parts.append(
            "Use the real tool results in the final answer and do not claim success that was not observed."
        )
        return " ".join(parts)
