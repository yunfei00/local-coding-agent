from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any

from agent.persistence.store import SQLiteStore


PROMPT_RULE_SCOPES = ("global", "project", "thread")
MAX_PROMPT_RULE_CHARS = 16_000


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def prompt_rule_key(scope: str, scope_id: str | None) -> str:
    if scope == "global":
        return "global"
    if scope not in {"project", "thread"}:
        raise ValueError(f"Unsupported prompt rule scope: {scope}")
    if not scope_id:
        raise ValueError(f"{scope} prompt rules require a scope id.")
    return f"{scope}:{scope_id}"


@dataclass(frozen=True)
class PromptRule:
    scope: str
    scope_id: str | None
    content: str
    enabled: bool
    updated_at: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class PromptRuleManager:
    def __init__(self, store: SQLiteStore) -> None:
        self.store = store

    def get(self, scope: str, scope_id: str | None = None) -> PromptRule | None:
        normalized_scope, normalized_id = self._normalize_target(scope, scope_id)
        row = self.store.get_prompt_rule(
            prompt_rule_key(normalized_scope, normalized_id)
        )
        return self._from_row(row) if row else None

    def set(
        self,
        scope: str,
        scope_id: str | None,
        content: str,
        *,
        enabled: bool = True,
    ) -> PromptRule:
        normalized_scope, normalized_id = self._normalize_target(scope, scope_id)
        normalized_content = str(content).strip()
        if not normalized_content:
            raise ValueError("Prompt rule content cannot be empty. Use reset to remove it.")
        if len(normalized_content) > MAX_PROMPT_RULE_CHARS:
            raise ValueError(
                f"Prompt rule content exceeds {MAX_PROMPT_RULE_CHARS} characters."
            )

        rule = PromptRule(
            scope=normalized_scope,
            scope_id=normalized_id,
            content=normalized_content,
            enabled=bool(enabled),
            updated_at=_now_iso(),
        )
        self.store.save_prompt_rule(
            rule_key=prompt_rule_key(rule.scope, rule.scope_id),
            scope=rule.scope,
            scope_id=rule.scope_id,
            content=rule.content,
            enabled=rule.enabled,
            updated_at=rule.updated_at,
        )
        return rule

    def toggle(
        self,
        scope: str,
        scope_id: str | None,
        enabled: bool,
    ) -> PromptRule:
        rule = self.get(scope, scope_id)
        if not rule:
            raise ValueError("Prompt rule does not exist.")
        return self.set(
            rule.scope,
            rule.scope_id,
            rule.content,
            enabled=enabled,
        )

    def reset(self, scope: str, scope_id: str | None = None) -> None:
        normalized_scope, normalized_id = self._normalize_target(scope, scope_id)
        self.store.delete_prompt_rule(
            prompt_rule_key(normalized_scope, normalized_id)
        )

    def hierarchy(
        self,
        *,
        project_id: str | None,
        thread_id: str | None,
    ) -> dict[str, PromptRule | None]:
        return {
            "global": self.get("global"),
            "project": (
                self.get("project", project_id)
                if project_id
                else None
            ),
            "thread": (
                self.get("thread", thread_id)
                if thread_id
                else None
            ),
        }

    def hierarchy_payload(
        self,
        *,
        project_id: str | None,
        thread_id: str | None,
    ) -> dict[str, Any]:
        rules = self.hierarchy(project_id=project_id, thread_id=thread_id)
        effective = [
            rule.to_dict()
            for rule in rules.values()
            if rule is not None and rule.enabled
        ]
        return {
            "global": rules["global"].to_dict() if rules["global"] else None,
            "project": rules["project"].to_dict() if rules["project"] else None,
            "thread": rules["thread"].to_dict() if rules["thread"] else None,
            "effective": effective,
        }

    def render_effective(
        self,
        *,
        project_id: str | None,
        thread_id: str | None,
    ) -> str:
        rules = self.hierarchy(project_id=project_id, thread_id=thread_id)
        sections: list[str] = []

        labels = (
            ("global", "Global rules"),
            ("project", "Project rules"),
            ("thread", "Thread rules"),
        )
        for key, label in labels:
            rule = rules[key]
            if rule is not None and rule.enabled:
                sections.append(f"### {label}\n{rule.content}")

        if not sections:
            return ""

        return (
            "User-configurable Prompt Rules follow. More-specific rules override "
            "less-specific rules when they conflict, but they never override runtime "
            "permission, approval, workspace-boundary, or safety enforcement.\n\n"
            + "\n\n".join(sections)
        )

    def _normalize_target(
        self,
        scope: str,
        scope_id: str | None,
    ) -> tuple[str, str | None]:
        normalized_scope = str(scope or "").strip().lower()
        if normalized_scope not in PROMPT_RULE_SCOPES:
            raise ValueError(
                "Prompt rule scope must be one of: global, project, thread."
            )

        normalized_id = (
            str(scope_id).strip()
            if scope_id is not None and str(scope_id).strip()
            else None
        )
        if normalized_scope == "global":
            return normalized_scope, None
        if not normalized_id:
            raise ValueError(
                f"{normalized_scope} prompt rules require a scope id."
            )
        return normalized_scope, normalized_id

    @staticmethod
    def _from_row(row: dict[str, Any]) -> PromptRule:
        return PromptRule(
            scope=str(row["scope"]),
            scope_id=(
                str(row["scope_id"])
                if row.get("scope_id") is not None
                else None
            ),
            content=str(row["content"]),
            enabled=bool(row["enabled"]),
            updated_at=str(row["updated_at"]),
        )
