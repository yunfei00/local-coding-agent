import tempfile
import unittest
from pathlib import Path

from agent.persistence.store import SQLiteStore
from agent.server.projects import ProjectRegistry


class SQLitePersistenceTests(unittest.TestCase):
    def test_projects_threads_messages_and_settings_survive_restart(self) -> None:
        with (
            tempfile.TemporaryDirectory() as data_root,
            tempfile.TemporaryDirectory() as first_project_root,
            tempfile.TemporaryDirectory() as second_project_root,
        ):
            store = SQLiteStore(data_root)
            registry = ProjectRegistry(store)

            first, first_thread, _ = registry.open(
                first_project_root,
                active_model="qwen3-coder:30b",
            )
            first.state.append_exchange(
                first_thread.id,
                user="first question",
                assistant="first answer",
            )
            first.state.set_thread_model(
                first_thread.id,
                "qwen3-coder:30b",
            )

            extra = first.state.create_thread(
                "Second thread",
                active_model="qwen3-coder:30b",
            )
            first.state.append_exchange(
                extra.id,
                user="second question",
                assistant="second answer",
            )
            registry.mark_active_thread(extra.id)

            second, second_thread, _ = registry.open(
                second_project_root,
                active_model="qwen3-coder:30b",
            )
            second.state.append_exchange(
                second_thread.id,
                user="project two",
                assistant="project two answer",
            )

            selected = registry.select(
                first.id,
                active_model="qwen3-coder:30b",
            )
            self.assertIsNotNone(selected)
            store.set_setting("permission_mode", "read_only")
            store.save_prompt_rule(
                rule_key="global",
                scope="global",
                scope_id=None,
                content="persisted global rule",
                enabled=True,
                updated_at="2026-09-29T00:00:00+00:00",
            )
            store.close()

            reopened_store = SQLiteStore(data_root)
            reopened = ProjectRegistry(reopened_store)

            self.assertEqual(len(reopened.list_projects()), 2)
            self.assertEqual(reopened.active_project_id, first.id)

            restored_first = reopened.get(first.id)
            self.assertIsNotNone(restored_first)
            assert restored_first is not None
            self.assertEqual(restored_first.active_thread_id, extra.id)
            self.assertEqual(len(restored_first.state.list_threads()), 2)
            self.assertEqual(
                restored_first.state.get_messages(first_thread.id),
                [
                    {"role": "user", "content": "first question"},
                    {"role": "assistant", "content": "first answer"},
                ],
            )
            self.assertEqual(
                restored_first.state.get_messages(extra.id)[-1]["content"],
                "second answer",
            )
            self.assertEqual(
                restored_first.state.get_thread(first_thread.id).active_model,
                "qwen3-coder:30b",
            )
            self.assertEqual(
                reopened_store.get_setting("permission_mode"),
                "read_only",
            )
            self.assertEqual(
                reopened_store.get_prompt_rule("global")["content"],
                "persisted global rule",
            )
            self.assertEqual(
                reopened_store.connection.execute("PRAGMA user_version").fetchone()[0],
                3,
            )
            reopened_store.close()

    def test_database_is_created_in_data_directory(self) -> None:
        with tempfile.TemporaryDirectory() as data_root:
            store = SQLiteStore(data_root)
            expected = Path(data_root) / "local-coding-agent.sqlite3"
            self.assertEqual(store.path, expected.resolve(strict=False))
            self.assertTrue(expected.exists())
            store.close()


if __name__ == "__main__":
    unittest.main()
