from __future__ import annotations

import json
import os
import re
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from agent.mcp.client import MCPServerConfig
from agent.persistence.store import SQLiteStore


_ENV_REF = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _json_object(value: Any, field: str) -> dict[str, str]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ValueError(f"{field} must be an object.")
    result: dict[str, str] = {}
    for key, item in value.items():
        name = str(key).strip()
        if not name:
            raise ValueError(f"{field} contains an empty key.")
        result[name] = str(item)
    return result


def _string_list(value: Any, field: str) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError(f"{field} must be an array.")
    result: list[str] = []
    for item in value:
        text = str(item).strip()
        if text and text not in result:
            result.append(text)
    return result


def _expand_env(value: str) -> str:
    return _ENV_REF.sub(
        lambda match: os.getenv(match.group(1), ""),
        value,
    )


@dataclass(frozen=True)
class MCPStoredServer:
    id: str
    name: str
    transport: str
    command: str | None
    args: tuple[str, ...]
    url: str | None
    env: dict[str, str]
    secret_env_keys: tuple[str, ...]
    enabled: bool
    trusted: bool
    timeout_seconds: float
    updated_at: str

    def to_public_dict(self) -> dict[str, Any]:
        return {
            **asdict(self),
            "args": list(self.args),
            "secret_env_keys": list(self.secret_env_keys),
            "secret_configured": False,
        }

    def to_client_config(
        self,
        *,
        secret_env: dict[str, str] | None = None,
    ) -> MCPServerConfig:
        env = {
            key: _expand_env(value)
            for key, value in self.env.items()
        }
        for key in self.secret_env_keys:
            if secret_env and key in secret_env:
                env[key] = secret_env[key]
            elif key in os.environ:
                env[key] = os.environ[key]
        return MCPServerConfig(
            name=self.name,
            transport=self.transport,  # type: ignore[arg-type]
            server_id=self.id,
            trusted=self.trusted,
            command=self.command,
            args=self.args,
            url=self.url,
            env=env,
            timeout_seconds=self.timeout_seconds,
        ).validate()


class MCPSettingsManager:
    def __init__(self, store: SQLiteStore) -> None:
        self.store = store

    def list(self) -> list[MCPStoredServer]:
        result: list[MCPStoredServer] = []
        for row in self.store.list_mcp_servers():
            result.append(
                MCPStoredServer(
                    id=str(row["id"]),
                    name=str(row["name"]),
                    transport=str(row["transport"]),
                    command=(
                        str(row["command"])
                        if row["command"] is not None
                        else None
                    ),
                    args=tuple(json.loads(str(row["args_json"]) or "[]")),
                    url=(
                        str(row["url"])
                        if row["url"] is not None
                        else None
                    ),
                    env=_json_object(
                        json.loads(str(row["env_json"]) or "{}"),
                        "env",
                    ),
                    secret_env_keys=tuple(
                        _string_list(
                            json.loads(
                                str(row["secret_env_keys_json"]) or "[]"
                            ),
                            "secret_env_keys",
                        )
                    ),
                    enabled=bool(row["enabled"]),
                    trusted=bool(row["trusted"]),
                    timeout_seconds=float(row["timeout_seconds"]),
                    updated_at=str(row["updated_at"]),
                )
            )
        return result

    def get(self, server_id: str) -> MCPStoredServer | None:
        for item in self.list():
            if item.id == server_id:
                return item
        return None

    def upsert(self, payload: dict[str, Any]) -> MCPStoredServer:
        server_id = str(payload.get("id") or "").strip() or (
            "mcp_" + uuid4().hex
        )
        name = str(payload.get("name") or "").strip()
        transport = str(payload.get("transport") or "").strip()
        command = str(payload.get("command") or "").strip() or None
        url = str(payload.get("url") or "").strip() or None
        args = tuple(_string_list(payload.get("args"), "args"))
        env = _json_object(payload.get("env"), "env")
        secret_env_keys = tuple(
            _string_list(
                payload.get("secret_env_keys"),
                "secret_env_keys",
            )
        )
        enabled = bool(payload.get("enabled", True))
        trusted = bool(payload.get("trusted", False))
        try:
            timeout_seconds = float(payload.get("timeout_seconds", 30))
        except (TypeError, ValueError) as exc:
            raise ValueError("timeout_seconds must be a number.") from exc

        if not name:
            raise ValueError("MCP server name cannot be empty.")
        if len(name) > 80:
            raise ValueError("MCP server name is too long.")
        if timeout_seconds <= 0 or timeout_seconds > 300:
            raise ValueError(
                "MCP timeout_seconds must be between 0 and 300."
            )
        if set(env).intersection(secret_env_keys):
            raise ValueError(
                "An MCP environment key cannot be both non-secret and secret."
            )

        probe = MCPServerConfig(
            name=name,
            transport=transport,  # type: ignore[arg-type]
            server_id=server_id,
            trusted=trusted,
            command=command,
            args=args,
            url=url,
            env=env,
            timeout_seconds=timeout_seconds,
        )
        probe.validate()

        updated_at = _now_iso()
        self.store.save_mcp_server(
            server_id=server_id,
            name=name,
            transport=transport,
            command=command,
            args_json=json.dumps(
                list(args),
                ensure_ascii=False,
                separators=(",", ":"),
            ),
            url=url,
            env_json=json.dumps(
                env,
                ensure_ascii=False,
                separators=(",", ":"),
            ),
            secret_env_keys_json=json.dumps(
                list(secret_env_keys),
                ensure_ascii=False,
                separators=(",", ":"),
            ),
            enabled=enabled,
            trusted=trusted,
            timeout_seconds=timeout_seconds,
            updated_at=updated_at,
        )
        item = self.get(server_id)
        if item is None:
            raise RuntimeError("MCP server was not persisted.")
        return item

    def delete(self, server_id: str) -> None:
        self.store.delete_mcp_server(server_id)
