import tempfile
import unittest

from agent.server.projects import ProjectRegistry


class ProjectRegistryTests(unittest.TestCase):
    def test_opening_project_creates_default_thread(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            registry = ProjectRegistry()
            project, thread, created = registry.open(
                root,
                active_model="qwen3-coder:30b",
            )

            self.assertTrue(created)
            self.assertEqual(registry.active_project_id, project.id)
            self.assertEqual(project.active_thread_id, thread.id)
            self.assertEqual(thread.active_model, "qwen3-coder:30b")
            self.assertEqual(len(project.state.list_threads()), 1)

    def test_multiple_projects_keep_independent_threads_and_messages(self) -> None:
        with tempfile.TemporaryDirectory() as first_root, tempfile.TemporaryDirectory() as second_root:
            registry = ProjectRegistry()

            first, first_thread, _ = registry.open(
                first_root,
                active_model="qwen3-coder:30b",
            )
            first.state.append_exchange(
                first_thread.id,
                user="first question",
                assistant="first answer",
            )
            extra = first.state.create_thread(
                "Second thread",
                active_model="qwen3-coder:30b",
            )

            second, second_thread, _ = registry.open(
                second_root,
                active_model="qwen3-coder:30b",
            )

            self.assertNotEqual(first.id, second.id)
            self.assertNotEqual(first_thread.id, second_thread.id)
            self.assertEqual(len(registry.list_projects()), 2)

            selected = registry.select(
                first.id,
                active_model="qwen3-coder:30b",
            )
            self.assertIsNotNone(selected)
            selected_project, selected_thread = selected

            self.assertEqual(selected_project.id, first.id)
            self.assertEqual(selected_thread.id, first_thread.id)
            self.assertEqual(len(selected_project.state.list_threads()), 2)
            self.assertIsNotNone(selected_project.state.get_thread(extra.id))
            self.assertEqual(
                selected_project.state.get_messages(first_thread.id),
                [
                    {"role": "user", "content": "first question"},
                    {"role": "assistant", "content": "first answer"},
                ],
            )

    def test_reopening_same_project_reuses_session(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            registry = ProjectRegistry()
            first, thread, created = registry.open(
                root,
                active_model="qwen3-coder:30b",
            )
            self.assertTrue(created)

            first.state.append_exchange(
                thread.id,
                user="hello",
                assistant="world",
            )

            reopened, reopened_thread, created_again = registry.open(
                root,
                active_model="qwen3-coder:30b",
            )

            self.assertFalse(created_again)
            self.assertEqual(reopened.id, first.id)
            self.assertEqual(reopened_thread.id, thread.id)
            self.assertEqual(
                reopened.state.get_messages(thread.id)[-1]["content"],
                "world",
            )


if __name__ == "__main__":
    unittest.main()
