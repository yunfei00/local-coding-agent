from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


DEFAULT_RESERVED_OUTPUT_TOKENS = 4_096
DEFAULT_CHARS_PER_TOKEN = 4
MESSAGE_OVERHEAD_TOKENS = 12
MIN_INPUT_BUDGET_TOKENS = 512
TRUNCATION_MARKER = "[Context truncated]"


def estimate_text_tokens(
    text: str,
    *,
    chars_per_token: int = DEFAULT_CHARS_PER_TOKEN,
) -> int:
    normalized = str(text or "")
    if not normalized:
        return 0
    divisor = max(int(chars_per_token), 1)
    return max(1, (len(normalized) + divisor - 1) // divisor)


def estimate_message_tokens(
    message: dict[str, Any],
    *,
    chars_per_token: int = DEFAULT_CHARS_PER_TOKEN,
) -> int:
    total = MESSAGE_OVERHEAD_TOKENS
    total += estimate_text_tokens(str(message.get("role") or ""), chars_per_token=chars_per_token)
    total += estimate_text_tokens(str(message.get("content") or ""), chars_per_token=chars_per_token)
    for key in ("name", "tool_name", "tool_call_id"):
        value = message.get(key)
        if value:
            total += estimate_text_tokens(str(value), chars_per_token=chars_per_token)
    tool_calls = message.get("tool_calls")
    if tool_calls:
        total += estimate_text_tokens(str(tool_calls), chars_per_token=chars_per_token)
    return total


@dataclass(frozen=True)
class ContextUsage:
    context_window_tokens: int
    reserved_output_tokens: int
    input_budget_tokens: int
    estimated_input_tokens: int
    history_messages_total: int
    history_messages_included: int
    omitted_history_messages: int
    runtime_messages_omitted: int = 0
    truncated_messages: int = 0
    context_sources: dict[str, int] = field(default_factory=dict)

    @property
    def utilization(self) -> float:
        if self.input_budget_tokens <= 0:
            return 0.0
        return min(self.estimated_input_tokens / self.input_budget_tokens, 1.0)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["utilization"] = round(self.utilization, 4)
        return payload


@dataclass(frozen=True)
class ContextSelection:
    messages: list[dict[str, Any]]
    usage: ContextUsage


class ContextBudgetManager:
    def __init__(
        self,
        *,
        context_window_tokens: int,
        reserved_output_tokens: int = DEFAULT_RESERVED_OUTPUT_TOKENS,
        chars_per_token: int = DEFAULT_CHARS_PER_TOKEN,
    ) -> None:
        self.context_window_tokens = max(int(context_window_tokens), 1_024)
        requested_reserve = max(int(reserved_output_tokens), 256)
        max_reserve = max(self.context_window_tokens // 2, 256)
        self.reserved_output_tokens = min(requested_reserve, max_reserve)
        self.input_budget_tokens = max(
            self.context_window_tokens - self.reserved_output_tokens,
            MIN_INPUT_BUDGET_TOKENS,
        )
        self.chars_per_token = max(int(chars_per_token), 1)

    def prepare_initial(
        self,
        *,
        system_prompt: str,
        history: list[dict[str, Any]],
        user_prompt: str,
        context_blocks: list[dict[str, str]] | None = None,
    ) -> ContextSelection:
        user_message = {"role": "user", "content": user_prompt}
        base_system_message = {"role": "system", "content": system_prompt}
        base_tokens = (
            self._message_tokens(base_system_message)
            + self._message_tokens(user_message)
        )
        remaining_context = max(self.input_budget_tokens - base_tokens, 0)
        system_parts = [system_prompt]
        source_tokens: dict[str, int] = {}

        for raw in context_blocks or []:
            source = str(raw.get("source") or "context").strip() or "context"
            content = str(raw.get("content") or "").strip()
            if not content or remaining_context <= 0:
                continue
            header = f"[Context source: {source}]"
            header_tokens = estimate_text_tokens(
                header,
                chars_per_token=self.chars_per_token,
            )
            if header_tokens >= remaining_context:
                break
            content_budget = remaining_context - header_tokens
            content_tokens = estimate_text_tokens(
                content,
                chars_per_token=self.chars_per_token,
            )
            selected = content
            if content_tokens > content_budget:
                max_chars = max(
                    content_budget * self.chars_per_token,
                    0,
                )
                if max_chars < 64:
                    continue
                marker = "\n[Context block truncated]"
                selected = content[: max(max_chars - len(marker), 1)] + marker
                content_tokens = estimate_text_tokens(
                    selected,
                    chars_per_token=self.chars_per_token,
                )

            system_parts.append(header + "\n" + selected)
            block_tokens = header_tokens + content_tokens
            remaining_context = max(remaining_context - block_tokens, 0)
            source_tokens[source] = (
                source_tokens.get(source, 0) + content_tokens
            )

        system_message = {
            "role": "system",
            "content": "\n\n".join(system_parts),
        }
        fixed_tokens = (
            self._message_tokens(system_message)
            + self._message_tokens(user_message)
        )
        remaining = max(self.input_budget_tokens - fixed_tokens, 0)

        selected_reversed: list[dict[str, Any]] = []
        used = 0
        for raw in reversed(history):
            message = dict(raw)
            cost = self._message_tokens(message)
            if used + cost > remaining:
                break
            selected_reversed.append(message)
            used += cost

        selected_history = list(reversed(selected_reversed))
        omitted = len(history) - len(selected_history)
        messages = [system_message, *selected_history, user_message]
        return ContextSelection(
            messages=messages,
            usage=self._usage(
                messages,
                history_total=len(history),
                history_included=len(selected_history),
                omitted_history=omitted,
                context_sources=source_tokens,
            ),
        )

    def fit_runtime(
        self,
        messages: list[dict[str, Any]],
        *,
        history_messages_total: int,
        context_sources: dict[str, int] | None = None,
    ) -> ContextSelection:
        if not messages:
            return ContextSelection(
                messages=[],
                usage=self._usage(
                    [],
                    history_total=history_messages_total,
                    history_included=0,
                    omitted_history=history_messages_total,
                    context_sources=context_sources,
                ),
            )

        system_message = dict(messages[0])
        latest_user_index = self._latest_user_index(messages)
        if latest_user_index <= 0:
            return self._truncate_to_budget(
                [dict(item) for item in messages],
                history_messages_total=history_messages_total,
                history_messages_included=max(len(messages) - 1, 0),
                omitted_history=0,
                context_sources=context_sources,
            )

        history = [dict(item) for item in messages[1:latest_user_index]]
        current_turn = [dict(item) for item in messages[latest_user_index:]]

        system_cost = self._message_tokens(system_message)
        current_turn, runtime_omitted, truncated = self._fit_current_turn(
            current_turn,
            max(self.input_budget_tokens - system_cost, 0),
        )
        current_cost = self._messages_tokens(current_turn)
        remaining = max(self.input_budget_tokens - system_cost - current_cost, 0)

        selected_reversed: list[dict[str, Any]] = []
        used = 0
        for message in reversed(history):
            cost = self._message_tokens(message)
            if used + cost > remaining:
                break
            selected_reversed.append(message)
            used += cost

        selected_history = list(reversed(selected_reversed))
        fitted = [system_message, *selected_history, *current_turn]
        omitted_history = max(history_messages_total - len(selected_history), 0)

        return ContextSelection(
            messages=fitted,
            usage=self._usage(
                fitted,
                history_total=history_messages_total,
                history_included=len(selected_history),
                omitted_history=omitted_history,
                runtime_omitted=runtime_omitted,
                truncated=truncated,
                context_sources=context_sources,
            ),
        )

    def _fit_current_turn(
        self,
        current_turn: list[dict[str, Any]],
        budget: int,
    ) -> tuple[list[dict[str, Any]], int, int]:
        if not current_turn:
            return [], 0, 0
        current = [dict(item) for item in current_turn]
        truncated = 0
        if self._messages_tokens(current) <= budget:
            return current, 0, truncated

        for max_chars in (8_000, 4_000, 2_000, 1_000):
            changed = 0
            compacted: list[dict[str, Any]] = []
            for message in current:
                if message.get("role") != "tool":
                    compacted.append(message)
                    continue
                next_message, was_truncated = self._truncate_message_content(
                    message,
                    max_chars=max_chars,
                )
                compacted.append(next_message)
                changed += int(was_truncated)
            current = compacted
            truncated = max(truncated, changed)
            if self._messages_tokens(current) <= budget:
                return current, 0, truncated

        user_message = current[0]
        groups = self._runtime_groups(current[1:])
        selected_reversed: list[list[dict[str, Any]]] = []
        used = self._message_tokens(user_message)
        for group in reversed(groups):
            group_cost = self._messages_tokens(group)
            if selected_reversed and used + group_cost > budget:
                break
            if not selected_reversed and used + group_cost > budget:
                latest_group = self._force_fit_group(group, max(budget - used, 0))
                selected_reversed.append(latest_group)
                used += self._messages_tokens(latest_group)
                break
            selected_reversed.append(group)
            used += group_cost

        selected_groups = list(reversed(selected_reversed))
        selected = [user_message]
        for group in selected_groups:
            selected.extend(group)
        selected_count = sum(len(group) for group in selected_groups)
        omitted = max(len(current) - 1 - selected_count, 0)
        return selected, omitted, truncated

    def _runtime_groups(self, messages: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
        groups: list[list[dict[str, Any]]] = []
        current: list[dict[str, Any]] = []
        for message in messages:
            if message.get("role") == "assistant" and current:
                groups.append(current)
                current = []
            current.append(message)
        if current:
            groups.append(current)
        return groups

    def _force_fit_group(
        self,
        group: list[dict[str, Any]],
        budget: int,
    ) -> list[dict[str, Any]]:
        if budget <= 0:
            return []
        fitted = [dict(item) for item in group]
        if self._messages_tokens(fitted) <= budget:
            return fitted

        for index in range(len(fitted) - 1, -1, -1):
            message = fitted[index]
            if message.get("role") == "tool":
                allowance_chars = max((budget - MESSAGE_OVERHEAD_TOKENS) * self.chars_per_token, 128)
                fitted[index], _ = self._truncate_message_content(
                    message,
                    max_chars=min(allowance_chars, 1_000),
                )
                if self._messages_tokens(fitted) <= budget:
                    return fitted

        while len(fitted) > 1 and self._messages_tokens(fitted) > budget:
            fitted.pop(0)

        if fitted and self._messages_tokens(fitted) > budget:
            fitted[-1], _ = self._truncate_message_content(
                fitted[-1],
                max_chars=max((budget - MESSAGE_OVERHEAD_TOKENS) * self.chars_per_token, 64),
            )
        return fitted

    def _truncate_to_budget(
        self,
        messages: list[dict[str, Any]],
        *,
        history_messages_total: int,
        history_messages_included: int,
        omitted_history: int,
        context_sources: dict[str, int] | None = None,
    ) -> ContextSelection:
        fitted = [dict(item) for item in messages]
        truncated = 0
        for index in range(len(fitted)):
            if self._messages_tokens(fitted) <= self.input_budget_tokens:
                break
            fitted[index], changed = self._truncate_message_content(
                fitted[index],
                max_chars=2_000,
            )
            truncated += int(changed)
        return ContextSelection(
            messages=fitted,
            usage=self._usage(
                fitted,
                history_total=history_messages_total,
                history_included=history_messages_included,
                omitted_history=omitted_history,
                truncated=truncated,
                context_sources=context_sources,
            ),
        )

    def _truncate_message_content(
        self,
        message: dict[str, Any],
        *,
        max_chars: int,
    ) -> tuple[dict[str, Any], bool]:
        next_message = dict(message)
        content = str(next_message.get("content") or "")
        if len(content) <= max_chars:
            return next_message, False
        keep = max(max_chars - len(TRUNCATION_MARKER) - 6, 0)
        if keep <= 0:
            next_message["content"] = TRUNCATION_MARKER
        else:
            head_chars = max(keep // 3, 1)
            tail_chars = max(keep - head_chars, 0)
            next_message["content"] = (
                content[:head_chars]
                + "\n"
                + TRUNCATION_MARKER
                + "\n"
                + (content[-tail_chars:] if tail_chars else "")
            )
        return next_message, True

    def _latest_user_index(self, messages: list[dict[str, Any]]) -> int:
        for index in range(len(messages) - 1, 0, -1):
            if messages[index].get("role") == "user":
                return index
        return -1

    def _message_tokens(self, message: dict[str, Any]) -> int:
        return estimate_message_tokens(message, chars_per_token=self.chars_per_token)

    def _messages_tokens(self, messages: list[dict[str, Any]]) -> int:
        return sum(self._message_tokens(message) for message in messages)

    def _usage(
        self,
        messages: list[dict[str, Any]],
        *,
        history_total: int,
        history_included: int,
        omitted_history: int,
        runtime_omitted: int = 0,
        truncated: int = 0,
        context_sources: dict[str, int] | None = None,
    ) -> ContextUsage:
        return ContextUsage(
            context_window_tokens=self.context_window_tokens,
            reserved_output_tokens=self.reserved_output_tokens,
            input_budget_tokens=self.input_budget_tokens,
            estimated_input_tokens=self._messages_tokens(messages),
            history_messages_total=history_total,
            history_messages_included=history_included,
            omitted_history_messages=omitted_history,
            runtime_messages_omitted=runtime_omitted,
            truncated_messages=truncated,
            context_sources=dict(context_sources or {}),
        )
