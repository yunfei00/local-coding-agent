"""Migrate a backup copy of the actual released v0.2 schema."""
import sqlite3
import tempfile
import unittest
from pathlib import Path

from agent.persistence.store import SQLiteStore


class V02ToV03MigrationTests(unittest.TestCase):
    def test_backup_upgrade_preserves_projects_threads_settings_and_rules(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            original = sqlite3.connect(root / "v02-original.sqlite3")
            original.executescript((Path(__file__).parent / "fixtures/v02-schema.sql").read_text(encoding="utf-8"))
            original.execute("INSERT INTO projects VALUES('p','/synthetic/project','now','now','t')")
            original.execute("INSERT INTO threads VALUES('t','p','会话标题','qwen2.5-coder:1.5b','now','now')")
            original.execute("INSERT INTO messages(thread_id,role,content,created_at) VALUES('t','user','保留消息','now')")
            original.execute("INSERT INTO settings VALUES('runtime.provider','\"ollama\"')")
            original.execute("INSERT INTO prompt_rules VALUES('global','global',NULL,'保留规则',1,'now')")
            original.commit()
            tables = ["projects", "threads", "messages", "settings", "prompt_rules"]
            before = {table: original.execute(f"SELECT * FROM {table}").fetchall() for table in tables}
            destination = root / "backup"
            destination.mkdir()
            backup = sqlite3.connect(destination / "local-coding-agent.sqlite3")
            original.backup(backup)
            backup.close()
            for restart in range(2):
                migrated = SQLiteStore(destination)
                after = {table: [tuple(row) for row in migrated.connection.execute(f"SELECT * FROM {table}")] for table in tables}
                self.assertEqual(after, before)
                self.assertEqual(migrated.connection.execute("PRAGMA quick_check").fetchone()[0], "ok")
                if restart == 0:
                    plan = migrated.task_plans.create("t", "升级后的计划", [{"description": "检查"}])
                    migrated.pin_context(thread_id="t", path="README.md", created_at="now")
                else:
                    self.assertEqual(migrated.task_plans.get(plan)["goal"], "升级后的计划")
                    self.assertEqual(len(migrated.list_pinned_context("t")), 1)
                migrated.close()
            self.assertEqual({table: original.execute(f"SELECT * FROM {table}").fetchall() for table in tables}, before)
            self.assertEqual(original.execute("SELECT name FROM sqlite_master WHERE name='task_plans'").fetchall(), [])
            original.close()
