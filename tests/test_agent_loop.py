import unittest

from agent.core.agent_loop import (
    ToolLoopGuard,
    canonical_tool_fingerprint,
    compact_tool_payload,
    trim_history,
)


class AgentLoopTests(unittest.TestCase):
    def test_tool_fingerprint_is_stable(self) -> None:
        first = canonical_tool_fingerprint(
            "read_file",
            {"start_line": 1, "path": "a.py"},
        )
        second = canonical_tool_fingerprint(
            "read_file",
            {"path": "a.py", "start_line": 1},
        )
        self.assertEqual(first, second)

    def test_repeated_identical_tool_call_is_blocked(self) -> None:
        guard = ToolLoopGuard(max_identical_calls=2)

        self.assertTrue(guard.register_call("read_file", {"path": "a.py"})[0])
        self.assertTrue(guard.register_call("read_file", {"path": "a.py"})[0])
        allowed, count, _ = guard.register_call(
            "read_file",
            {"path": "a.py"},
        )

        self.assertFalse(allowed)
        self.assertEqual(count, 3)
        self.assertEqual(guard.blocked_repeats, 1)

    def test_completion_requires_diff_and_validation_after_code_change(self) -> None:
        guard = ToolLoopGuard()
        guard.record_result(
            "apply_patch",
            {
                "ok": True,
                "changed_paths": ["src/app.py"],
            },
        )

        self.assertEqual(
            guard.completion_gaps(),
            ["git_diff", "validation"],
        )

        guard.record_result(
            "git_diff",
            {"ok": True, "changed_paths": []},
        )
        self.assertEqual(guard.completion_gaps(), ["validation"])

        guard.record_result(
            "run_command",
            {
                "ok": True,
                "exit_code": 0,
                "changed_paths": [],
            },
        )
        self.assertEqual(guard.completion_gaps(), [])

    def test_document_change_does_not_force_test_command(self) -> None:
        guard = ToolLoopGuard()
        guard.record_result(
            "write_file",
            {
                "ok": True,
                "changed_paths": ["README.md"],
            },
        )
        self.assertEqual(guard.completion_gaps(), ["git_diff"])

    def test_history_keeps_recent_messages(self) -> None:
        history = [
            {"role": "user", "content": "old-" + ("x" * 100)},
            {"role": "assistant", "content": "middle-" + ("y" * 100)},
            {"role": "user", "content": "new-" + ("z" * 100)},
        ]
        trimmed = trim_history(history, max_chars=180)

        self.assertEqual(trimmed[-1]["content"], history[-1]["content"])
        self.assertLess(len(trimmed), len(history))

    def test_large_tool_payload_is_compacted(self) -> None:
        payload = {
            "ok": False,
            "summary": "tests failed",
            "stdout": "A" * 50_000,
            "stderr": "B" * 50_000,
            "exit_code": 1,
            "changed_paths": [],
        }

        compacted = compact_tool_payload(payload, max_chars=12_000)
        self.assertTrue(compacted["truncated_for_model"])
        self.assertLess(
            len(str(compacted.get("stdout_tail", ""))),
            9_000,
        )


if __name__ == "__main__":
    unittest.main()
