from __future__ import annotations

import os
import sqlite3
from pathlib import Path
from typing import Any


SCHEMA_VERSION = 3


def default_data_dir() -> Path:
    configured = os.getenv("LCA_DATA_DIR")
    if configured:
        return Path(configured).expanduser().resolve(strict=False)
    return (Path.home() / ".local-coding-agent").resolve(strict=False)


class SQLiteStore:
    def __init__(self, data_dir: str | Path | None = None) -> None:
        self.data_dir = (
            Path(data_dir).expanduser().resolve(strict=False)
            if data_dir is not None
            else default_data_dir()
        )
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.path = self.data_dir / "local-coding-agent.sqlite3"
        self.connection = sqlite3.connect(self.path)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA foreign_keys = ON")
        self.connection.execute("PRAGMA journal_mode = WAL")
        self.connection.execute("PRAGMA synchronous = NORMAL")
        self._migrate()

    def _migrate(self) -> None:
        self.connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS projects (
                id TEXT PRIMARY KEY,
                path TEXT NOT NULL UNIQUE,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                active_thread_id TEXT
            );

            CREATE TABLE IF NOT EXISTS threads (
                id TEXT PRIMARY KEY,
                project_id TEXT NOT NULL,
                title TEXT NOT NULL,
                active_model TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE CASCADE
            );

            CREATE INDEX IF NOT EXISTS idx_threads_project_updated
            ON threads(project_id, updated_at DESC);

            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                thread_id TEXT NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY(thread_id) REFERENCES threads(id) ON DELETE CASCADE
            );

            CREATE INDEX IF NOT EXISTS idx_messages_thread_id
            ON messages(thread_id, id);

            CREATE TABLE IF NOT EXISTS tool_calls (
                id TEXT PRIMARY KEY,
                thread_id TEXT,
                turn_id TEXT,
                tool_name TEXT NOT NULL,
                arguments_json TEXT NOT NULL,
                result_json TEXT,
                status TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS approvals (
                id TEXT PRIMARY KEY,
                thread_id TEXT,
                turn_id TEXT,
                tool_name TEXT NOT NULL,
                decision TEXT,
                risk TEXT,
                created_at TEXT NOT NULL,
                resolved_at TEXT
            );

            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS prompt_rules (
                rule_key TEXT PRIMARY KEY,
                scope TEXT NOT NULL,
                scope_id TEXT,
                content TEXT NOT NULL,
                enabled INTEGER NOT NULL DEFAULT 1,
                updated_at TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_prompt_rules_scope
            ON prompt_rules(scope, scope_id);

            CREATE TABLE IF NOT EXISTS mcp_servers (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL UNIQUE,
                transport TEXT NOT NULL,
                command TEXT,
                args_json TEXT NOT NULL DEFAULT '[]',
                url TEXT,
                env_json TEXT NOT NULL DEFAULT '{}',
                secret_env_keys_json TEXT NOT NULL DEFAULT '[]',
                enabled INTEGER NOT NULL DEFAULT 1,
                trusted INTEGER NOT NULL DEFAULT 0,
                timeout_seconds REAL NOT NULL DEFAULT 30,
                updated_at TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_mcp_servers_name
            ON mcp_servers(name);
            """
        )
        self.connection.execute(
            "PRAGMA user_version = " + str(SCHEMA_VERSION)
        )
        self.connection.commit()

    def close(self) -> None:
        self.connection.close()

    def get_setting(self, key: str) -> str | None:
        row = self.connection.execute(
            "SELECT value FROM settings WHERE key = ?",
            (key,),
        ).fetchone()
        return str(row["value"]) if row else None

    def set_setting(self, key: str, value: str) -> None:
        self.connection.execute(
            """
            INSERT INTO settings(key, value)
            VALUES(?, ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value
            """,
            (key, value),
        )
        self.connection.commit()

    def save_mcp_server(
        self,
        *,
        server_id: str,
        name: str,
        transport: str,
        command: str | None,
        args_json: str,
        url: str | None,
        env_json: str,
        secret_env_keys_json: str,
        enabled: bool,
        trusted: bool,
        timeout_seconds: float,
        updated_at: str,
    ) -> None:
        self.connection.execute(
            """
            INSERT INTO mcp_servers(
                id, name, transport, command, args_json, url, env_json,
                secret_env_keys_json, enabled, trusted, timeout_seconds,
                updated_at
            )
            VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                name = excluded.name,
                transport = excluded.transport,
                command = excluded.command,
                args_json = excluded.args_json,
                url = excluded.url,
                env_json = excluded.env_json,
                secret_env_keys_json = excluded.secret_env_keys_json,
                enabled = excluded.enabled,
                trusted = excluded.trusted,
                timeout_seconds = excluded.timeout_seconds,
                updated_at = excluded.updated_at
            """,
            (
                server_id,
                name,
                transport,
                command,
                args_json,
                url,
                env_json,
                secret_env_keys_json,
                1 if enabled else 0,
                1 if trusted else 0,
                float(timeout_seconds),
                updated_at,
            ),
        )
        self.connection.commit()

    def list_mcp_servers(self) -> list[dict[str, Any]]:
        rows = self.connection.execute(
            """
            SELECT
                id, name, transport, command, args_json, url, env_json,
                secret_env_keys_json, enabled, trusted, timeout_seconds,
                updated_at
            FROM mcp_servers
            ORDER BY name COLLATE NOCASE ASC
            """
        ).fetchall()
        return [dict(row) for row in rows]

    def delete_mcp_server(self, server_id: str) -> None:
        self.connection.execute(
            "DELETE FROM mcp_servers WHERE id = ?",
            (server_id,),
        )
        self.connection.commit()

    def save_project(
        self,
        *,
        project_id: str,
        path: str,
        created_at: str,
        updated_at: str,
        active_thread_id: str | None,
    ) -> None:
        self.connection.execute(
            """
            INSERT INTO projects(
                id, path, created_at, updated_at, active_thread_id
            )
            VALUES(?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                path = excluded.path,
                updated_at = excluded.updated_at,
                active_thread_id = excluded.active_thread_id
            """,
            (
                project_id,
                path,
                created_at,
                updated_at,
                active_thread_id,
            ),
        )
        self.connection.commit()

    def list_projects(self) -> list[dict[str, Any]]:
        rows = self.connection.execute(
            """
            SELECT id, path, created_at, updated_at, active_thread_id
            FROM projects
            ORDER BY updated_at DESC
            """
        ).fetchall()
        return [dict(row) for row in rows]

    def save_thread(
        self,
        *,
        thread_id: str,
        project_id: str,
        title: str,
        active_model: str | None,
        created_at: str,
        updated_at: str,
    ) -> None:
        self.connection.execute(
            """
            INSERT INTO threads(
                id, project_id, title, active_model, created_at, updated_at
            )
            VALUES(?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                title = excluded.title,
                active_model = excluded.active_model,
                updated_at = excluded.updated_at
            """,
            (
                thread_id,
                project_id,
                title,
                active_model,
                created_at,
                updated_at,
            ),
        )
        self.connection.commit()

    def list_threads(self, project_id: str) -> list[dict[str, Any]]:
        rows = self.connection.execute(
            """
            SELECT id, project_id, title, active_model, created_at, updated_at
            FROM threads
            WHERE project_id = ?
            ORDER BY updated_at DESC
            """,
            (project_id,),
        ).fetchall()
        return [dict(row) for row in rows]

    def append_message(
        self,
        *,
        thread_id: str,
        role: str,
        content: str,
        created_at: str,
    ) -> None:
        self.connection.execute(
            """
            INSERT INTO messages(thread_id, role, content, created_at)
            VALUES(?, ?, ?, ?)
            """,
            (thread_id, role, content, created_at),
        )
        self.connection.commit()

    def list_messages(self, thread_id: str) -> list[dict[str, str]]:
        rows = self.connection.execute(
            """
            SELECT role, content
            FROM messages
            WHERE thread_id = ?
            ORDER BY id ASC
            """,
            (thread_id,),
        ).fetchall()
        return [
            {
                "role": str(row["role"]),
                "content": str(row["content"]),
            }
            for row in rows
        ]

    def save_prompt_rule(
        self,
        *,
        rule_key: str,
        scope: str,
        scope_id: str | None,
        content: str,
        enabled: bool,
        updated_at: str,
    ) -> None:
        self.connection.execute(
            """
            INSERT INTO prompt_rules(
                rule_key, scope, scope_id, content, enabled, updated_at
            )
            VALUES(?, ?, ?, ?, ?, ?)
            ON CONFLICT(rule_key) DO UPDATE SET
                scope = excluded.scope,
                scope_id = excluded.scope_id,
                content = excluded.content,
                enabled = excluded.enabled,
                updated_at = excluded.updated_at
            """,
            (
                rule_key,
                scope,
                scope_id,
                content,
                1 if enabled else 0,
                updated_at,
            ),
        )
        self.connection.commit()

    def get_prompt_rule(self, rule_key: str) -> dict[str, Any] | None:
        row = self.connection.execute(
            """
            SELECT rule_key, scope, scope_id, content, enabled, updated_at
            FROM prompt_rules
            WHERE rule_key = ?
            """,
            (rule_key,),
        ).fetchone()
        return dict(row) if row else None

    def delete_prompt_rule(self, rule_key: str) -> None:
        self.connection.execute(
            "DELETE FROM prompt_rules WHERE rule_key = ?",
            (rule_key,),
        )
        self.connection.commit()

    def delete_project(self, project_id: str) -> None:
        self.connection.execute(
            """
            DELETE FROM prompt_rules
            WHERE (scope = 'project' AND scope_id = ?)
               OR (
                    scope = 'thread'
                    AND scope_id IN (
                        SELECT id FROM threads WHERE project_id = ?
                    )
               )
            """,
            (project_id, project_id),
        )
        self.connection.execute(
            "DELETE FROM projects WHERE id = ?",
            (project_id,),
        )
        self.connection.commit()
