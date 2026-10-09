from __future__ import annotations

import os
from pathlib import Path
import re
from typing import Any
from urllib.parse import urlsplit, urlunsplit


_SECRET_PATTERNS = (
    re.compile(r"(?i)(authorization\s*[:=]\s*bearer\s+)[^\s,;]+"),
    re.compile(r"(?i)(bearer\s+)[A-Za-z0-9._~+/=-]+"),
    re.compile(
        r"(?i)((?:api[_-]?key|access[_-]?token|secret|password)\s*[:=]\s*)"
        r"[^\s,;]+"
    ),
    re.compile(r"\bsk-[A-Za-z0-9_-]{8,}\b"),
)


def redact_path(value: str | Path | None) -> str | None:
    if value is None:
        return None
    text = str(value)
    home = str(Path.home())
    if home and text.lower().startswith(home.lower()):
        suffix = text[len(home) :].lstrip("\\/")
        return "<HOME>" + (os.sep + suffix if suffix else "")
    return text


def redact_url(value: str | None) -> str | None:
    if not value:
        return value
    try:
        parsed = urlsplit(value)
    except ValueError:
        return redact_text(value)

    hostname = parsed.hostname or ""
    if not hostname:
        return redact_text(value)

    port = f":{parsed.port}" if parsed.port is not None else ""
    netloc = hostname + port
    return urlunsplit(
        (
            parsed.scheme,
            netloc,
            parsed.path,
            "",
            "",
        )
    )


def redact_text(
    value: str | None,
    *,
    exact_secrets: tuple[str, ...] = (),
    max_chars: int = 500,
) -> str:
    text = str(value or "")
    for secret in exact_secrets:
        if secret:
            text = text.replace(secret, "<REDACTED>")
    home = str(Path.home())
    if home:
        text = re.sub(
            re.escape(home),
            "<HOME>",
            text,
            flags=re.IGNORECASE,
        )
    for pattern in _SECRET_PATTERNS:
        text = pattern.sub(
            lambda match: (
                (match.group(1) if match.lastindex else "")
                + "<REDACTED>"
            ),
            text,
        )
    if len(text) > max_chars:
        return text[:max_chars] + "…"
    return text


def database_summary(store: Any) -> dict[str, Any]:
    counts: dict[str, int] = {}
    for table in (
        "projects",
        "threads",
        "messages",
        "tool_calls",
        "approvals",
        "prompt_rules",
        "settings",
        "mcp_servers",
        "pinned_context",
    ):
        row = store.connection.execute(
            f"SELECT COUNT(*) AS count FROM {table}"
        ).fetchone()
        counts[table] = int(row["count"] if row else 0)

    integrity_row = store.connection.execute(
        "PRAGMA quick_check"
    ).fetchone()
    schema_row = store.connection.execute(
        "PRAGMA user_version"
    ).fetchone()

    try:
        size_bytes = int(store.path.stat().st_size)
    except OSError:
        size_bytes = 0

    return {
        "path": redact_path(store.path),
        "schema_version": int(schema_row[0] if schema_row else 0),
        "size_bytes": size_bytes,
        "quick_check": (
            str(integrity_row[0])
            if integrity_row
            else "unknown"
        ),
        "counts": counts,
    }


def prompt_rules_summary(
    hierarchy: dict[str, Any],
) -> dict[str, dict[str, bool]]:
    result: dict[str, dict[str, bool]] = {}
    for scope in ("global", "project", "thread"):
        rule = hierarchy.get(scope)
        result[scope] = {
            "configured": rule is not None,
            "enabled": bool(rule.enabled) if rule is not None else False,
        }
    return result


def sanitize_provider_status(
    status: dict[str, Any],
    *,
    exact_secrets: tuple[str, ...] = (),
) -> dict[str, Any]:
    models = status.get("models")
    model_names = [
        str(item.get("name"))
        for item in models
        if isinstance(item, dict) and item.get("name")
    ] if isinstance(models, list) else []

    error = status.get("error")
    safe_error = None
    if isinstance(error, dict):
        safe_error = {
            "code": str(error.get("code") or ""),
            "message": redact_text(
                str(error.get("message") or ""),
                exact_secrets=exact_secrets,
            ),
        }

    return {
        "provider": str(status.get("provider") or ""),
        "online": bool(status.get("online")),
        "base_url": redact_url(
            str(status.get("base_url") or "")
        ),
        "default_model": status.get("default_model"),
        "preferred_model": status.get("preferred_model"),
        "context_window": status.get("context_window"),
        "model_count": len(model_names),
        "models": model_names[:20],
        "models_truncated": len(model_names) > 20,
        "error": safe_error,
    }
