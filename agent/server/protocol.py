from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import uuid4


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex}"


def envelope(
    message_type: str,
    payload: dict[str, Any] | None = None,
    *,
    request_id: str | None = None,
    thread_id: str | None = None,
    turn_id: str | None = None,
) -> dict[str, Any]:
    return {
        "type": message_type,
        "request_id": request_id,
        "thread_id": thread_id,
        "turn_id": turn_id,
        "timestamp": utc_now_iso(),
        "payload": payload or {},
    }


def validate_client_message(message: Any) -> tuple[bool, str | None]:
    if not isinstance(message, dict):
        return False, "message_must_be_object"
    if not isinstance(message.get("type"), str) or not message["type"]:
        return False, "type_is_required"
    if "payload" in message and not isinstance(message["payload"], dict):
        return False, "payload_must_be_object"
    return True, None
