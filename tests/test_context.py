from __future__ import annotations

import unittest

from agent.core.context import ContextBudgetManager, estimate_message_tokens


class ContextBudgetManagerTests(unittest.TestCase):
    def test_short_history_is_unchanged(self) -> None:
        manager = ContextBudgetManager(
            context_window_tokens=8192,
            reserved_output_tokens=1024,
        )
        history = [
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "hi"},
        ]
        selection = manager.prepare_initial(
            system_prompt="SYSTEM",
            history=history,
            user_prompt="current",
        )

        self.assertEqual(selection.messages[0]["content"], "SYSTEM")
        self.assertEqual(selection.messages[1:3], history)
        self.assertEqual(selection.messages[-1]["content"], "current")
        self.assertEqual(selection.usage.omitted_history_messages, 0)

    def test_long_history_keeps_recent_messages_and_stays_in_budget(self) -> None:
        manager = ContextBudgetManager(
            context_window_tokens=2048,
            reserved_output_tokens=512,
        )
        history = [
            {
                "role": "user" if index % 2 == 0 else "assistant",
                "content": f"message-{index}-" + ("x" * 900),
            }
            for index in range(40)
        ]

        selection = manager.prepare_initial(
            system_prompt="SYSTEM-RULES",
            history=history,
            user_prompt="LATEST-USER-INTENT",
        )

        self.assertEqual(selection.messages[0]["content"], "SYSTEM-RULES")
        self.assertEqual(selection.messages[-1]["content"], "LATEST-USER-INTENT")
        self.assertGreater(selection.usage.omitted_history_messages, 0)
        self.assertIn("message-39-", selection.messages[-2]["content"])
        self.assertLessEqual(
            selection.usage.estimated_input_tokens,
            selection.usage.input_budget_tokens,
        )

    def test_runtime_keeps_latest_tool_result(self) -> None:
        manager = ContextBudgetManager(
            context_window_tokens=2048,
            reserved_output_tokens=512,
        )
        messages = [
            {"role": "system", "content": "SYSTEM"},
            {"role": "user", "content": "old question " + ("a" * 1200)},
            {"role": "assistant", "content": "old answer " + ("b" * 1200)},
            {"role": "user", "content": "CURRENT TASK"},
        ]
        for index in range(8):
            messages.extend(
                [
                    {
                        "role": "assistant",
                        "content": "",
                        "tool_calls": [
                            {
                                "type": "function",
                                "function": {
                                    "name": "read_file",
                                    "arguments": {"path": f"file-{index}.txt"},
                                },
                            }
                        ],
                    },
                    {
                        "role": "tool",
                        "tool_name": "read_file",
                        "content": f"TOOL-{index}-" + ("z" * 5000),
                    },
                ]
            )

        selection = manager.fit_runtime(
            messages,
            history_messages_total=2,
        )
        serialized = str(selection.messages)

        self.assertIn("SYSTEM", serialized)
        self.assertIn("CURRENT TASK", serialized)
        self.assertIn("TOOL-7-", serialized)
        self.assertLessEqual(
            selection.usage.estimated_input_tokens,
            selection.usage.input_budget_tokens,
        )
        self.assertTrue(
            selection.usage.runtime_messages_omitted > 0
            or selection.usage.truncated_messages > 0
        )

    def test_message_estimate_counts_tool_metadata(self) -> None:
        plain = estimate_message_tokens(
            {"role": "assistant", "content": ""}
        )
        with_tool = estimate_message_tokens(
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {
                        "type": "function",
                        "function": {
                            "name": "read_file",
                            "arguments": {"path": "README.md"},
                        },
                    }
                ],
            }
        )
        self.assertGreater(with_tool, plain)


if __name__ == "__main__":
    unittest.main()
