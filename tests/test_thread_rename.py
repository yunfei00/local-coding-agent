import unittest
from agent.server.state import InMemoryState


class ThreadRenameTests(unittest.TestCase):
    def test_rename_persists_in_state_and_preserves_messages(self):
        state = InMemoryState()
        thread = state.create_thread()
        state.append_exchange(thread.id, user="hello", assistant="world")
        renamed = state.rename_thread(thread.id, "  项目导航   优化  ")
        self.assertEqual(renamed.title, "项目导航 优化")
        self.assertEqual(len(state.get_messages(thread.id)), 2)
        self.assertEqual(state.list_threads()[0].title, "项目导航 优化")

    def test_invalid_names_do_not_change_title(self):
        state = InMemoryState()
        thread = state.create_thread()
        self.assertIsNone(state.rename_thread(thread.id, "   "))
        self.assertIsNone(state.rename_thread(thread.id, "x" * 121))
        self.assertIsNone(state.rename_thread("missing", "new"))
        self.assertEqual(thread.title, "New thread")


if __name__ == "__main__":
    unittest.main()
