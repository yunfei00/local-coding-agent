import unittest

from agent.server.state import InMemoryState


class ThreadTitleTests(unittest.TestCase):
    def test_first_prompt_names_thread_and_does_not_overwrite(self):
        state = InMemoryState()
        thread = state.create_thread()
        named = state.summarize_thread_title(thread.id, "  修复项目侧边栏\n  缩进问题  ")
        self.assertEqual(named.title, "修复项目侧边栏 缩进问题")
        state.summarize_thread_title(thread.id, "完全不同的后续任务")
        self.assertEqual(state.get_thread(thread.id).title, named.title)

    def test_title_is_short_and_empty_prompt_does_not_rename(self):
        state = InMemoryState()
        thread = state.create_thread()
        self.assertIsNone(state.summarize_thread_title(thread.id, "  "))
        self.assertEqual(thread.title, "New thread")
        self.assertLessEqual(len(state.summarize_thread_title(thread.id, "A" * 100).title), 46)


if __name__ == "__main__":
    unittest.main()
