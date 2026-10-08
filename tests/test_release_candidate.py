from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
import tomllib

from agent.core.version import APP_VERSION
from agent.persistence.store import SCHEMA_VERSION, SQLiteStore
from agent.permissions.policy import PermissionMode, PermissionPolicy
from agent.server.main import SYSTEM_PROMPT
from agent.tools.workspace import Workspace


class ReleaseCandidateVersionTests(unittest.TestCase):
    def test_all_runtime_versions_are_v020(self) -> None:
        root = Path(__file__).resolve().parents[1]
        root_package = json.loads((root / "package.json").read_text(encoding="utf-8"))
        desktop_package = json.loads((root / "desktop" / "package.json").read_text(encoding="utf-8"))
        pyproject = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))

        self.assertEqual(APP_VERSION, "0.2.0")
        self.assertEqual(root_package["version"], APP_VERSION)
        self.assertEqual(desktop_package["version"], APP_VERSION)
        self.assertEqual(pyproject["project"]["version"], APP_VERSION)

    def test_system_prompt_requires_explicit_git_publish_intent(self) -> None:
        lower = SYSTEM_PROMPT.lower()
        self.assertIn("never create a git commit", lower)
        self.assertIn("explicitly asks", lower)

    def test_git_commit_and_push_require_approval(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            workspace = Workspace(root)
            policy = PermissionPolicy(PermissionMode.WORKSPACE)

            commit = policy.evaluate(
                tool_name="run_command",
                arguments={"command": 'git commit -m "agent change"'},
                workspace=workspace,
            )
            push = policy.evaluate(
                tool_name="run_command",
                arguments={"command": "git -C . push origin main"},
                workspace=workspace,
            )

            self.assertTrue(commit.allowed)
            self.assertTrue(commit.requires_approval)
            self.assertEqual(commit.risk, "git_commit")
            self.assertTrue(push.allowed)
            self.assertTrue(push.requires_approval)
            self.assertEqual(push.risk, "git_publish")


class V01DatabaseUpgradeTests(unittest.TestCase):
    def test_v01_schema_migrates_to_current_without_data_loss(self) -> None:
        with tempfile.TemporaryDirectory() as data_root:
            database = Path(data_root) / "local-coding-agent.sqlite3"
            connection = sqlite3.connect(database)
            connection.executescript(
                """
                PRAGMA user_version = 1;
                CREATE TABLE projects (
                    id TEXT PRIMARY KEY,
                    path TEXT NOT NULL UNIQUE,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    active_thread_id TEXT
                );
                CREATE TABLE threads (
                    id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL,
                    title TEXT NOT NULL,
                    active_model TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    thread_id TEXT NOT NULL,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE tool_calls (
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
                CREATE TABLE approvals (
                    id TEXT PRIMARY KEY,
                    thread_id TEXT,
                    turn_id TEXT,
                    tool_name TEXT NOT NULL,
                    decision TEXT,
                    risk TEXT,
                    created_at TEXT NOT NULL,
                    resolved_at TEXT
                );
                CREATE TABLE settings (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
                """
            )
            connection.execute(
                """
                INSERT INTO projects(
                    id, path, created_at, updated_at, active_thread_id
                ) VALUES('project-1', ?, 'old', 'old', 'thread-1')
                """,
                (str(Path(data_root) / "workspace"),),
            )
            connection.execute(
                """
                INSERT INTO threads(
                    id, project_id, title, active_model, created_at, updated_at
                ) VALUES(
                    'thread-1', 'project-1', 'v0.1 thread',
                    'qwen3-coder:30b', 'old', 'old'
                )
                """
            )
            connection.execute(
                """
                INSERT INTO messages(thread_id, role, content, created_at)
                VALUES('thread-1', 'user', 'preserve me', 'old')
                """
            )
            connection.execute(
                "INSERT INTO settings(key, value) VALUES('permission_mode', 'read_only')"
            )
            connection.commit()
            connection.close()

            store = SQLiteStore(data_root)
            try:
                version = store.connection.execute("PRAGMA user_version").fetchone()[0]
                integrity = store.connection.execute("PRAGMA quick_check").fetchone()[0]
                message = store.connection.execute(
                    "SELECT content FROM messages WHERE thread_id = 'thread-1'"
                ).fetchone()["content"]
                permission = store.get_setting("permission_mode")
                prompt_rules_table = store.connection.execute(
                    """
                    SELECT name FROM sqlite_master
                    WHERE type='table' AND name='prompt_rules'
                    """
                ).fetchone()

                self.assertEqual(version, SCHEMA_VERSION)
                self.assertEqual(version, 3)
                self.assertEqual(integrity, "ok")
                self.assertEqual(message, "preserve me")
                self.assertEqual(permission, "read_only")
                self.assertIsNotNone(prompt_rules_table)
                mcp_table = store.connection.execute(
                    """
                    SELECT name FROM sqlite_master
                    WHERE type='table' AND name='mcp_servers'
                    """
                ).fetchone()
                self.assertIsNotNone(mcp_table)
            finally:
                store.close()


if __name__ == "__main__":
    unittest.main()
