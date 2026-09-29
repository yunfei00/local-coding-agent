from __future__ import annotations

import asyncio
import tempfile
import unittest

from agent.tools.base import ToolError
from agent.tools.shell import RunCommandTool
from agent.tools.stream import ToolStreamState
from agent.tools.workspace import Workspace


class ToolStreamStateTests(unittest.TestCase):
    def test_sequences_are_monotonic_and_output_is_bounded(self) -> None:
        state = ToolStreamState(max_live_chars=10)

        events = [
            state.meta("process_started", pid=123),
            *state.output("stdout", "abcdef"),
            *state.output("stderr", "ghijkl"),
        ]

        sequences = [event["sequence"] for event in events]
        self.assertEqual(sequences, sorted(sequences))
        self.assertEqual(sequences, list(range(1, len(events) + 1)))
        self.assertTrue(state.truncated)
        self.assertEqual(state.live_chars, 10)
        self.assertEqual(state.total_chars, 12)
        self.assertEqual(
            [event["event"] for event in events if event["stream"] == "meta"],
            ["process_started", "stream_truncated"],
        )


class RunCommandStreamTests(unittest.IsolatedAsyncioTestCase):
    async def test_command_emits_ordered_lifecycle_and_output(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            events: list[dict] = []

            async def on_output(chunk: dict) -> None:
                events.append(dict(chunk))

            result = await RunCommandTool(Workspace(root)).execute(
                {
                    "command": (
                        "python -c \"import sys; "
                        "print('stdout-line', flush=True); "
                        "print('stderr-line', file=sys.stderr, flush=True)\""
                    ),
                    "timeout_seconds": 30,
                },
                on_output=on_output,
            )

            self.assertTrue(result.ok)
            sequences = [event["sequence"] for event in events]
            self.assertEqual(sequences, sorted(sequences))
            self.assertEqual(len(sequences), len(set(sequences)))
            self.assertEqual(events[0]["event"], "process_started")
            self.assertEqual(events[-1]["event"], "process_exited")
            self.assertTrue(
                any(
                    event.get("stream") == "stdout"
                    and "stdout-line" in event.get("text", "")
                    for event in events
                )
            )
            self.assertTrue(
                any(
                    event.get("stream") == "stderr"
                    and "stderr-line" in event.get("text", "")
                    for event in events
                )
            )
            self.assertIn("stream", result.data)
            self.assertFalse(result.data["stream"]["truncated"])

    async def test_timeout_reports_process_tree_termination(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            events: list[dict] = []

            async def on_output(chunk: dict) -> None:
                events.append(dict(chunk))

            with self.assertRaises(ToolError) as ctx:
                await RunCommandTool(Workspace(root)).execute(
                    {
                        "command": 'python -c "import time; time.sleep(5)"',
                        "timeout_seconds": 1,
                    },
                    on_output=on_output,
                )

            self.assertEqual(ctx.exception.code, "COMMAND_TIMEOUT")
            meta_events = [
                event.get("event")
                for event in events
                if event.get("stream") == "meta"
            ]
            self.assertIn("process_terminating", meta_events)
            self.assertIn("process_terminated", meta_events)

            terminated = next(
                event
                for event in events
                if event.get("event") == "process_terminated"
            )
            self.assertEqual(terminated["reason"], "timeout")
            self.assertIn(
                terminated["method"],
                {"taskkill", "kill", "sigterm", "sigkill", "already_exited"},
            )

    async def test_cancellation_reports_process_tree_termination(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            events: list[dict] = []
            started = asyncio.Event()

            async def on_output(chunk: dict) -> None:
                events.append(dict(chunk))
                if chunk.get("event") == "process_started":
                    started.set()

            task = asyncio.create_task(
                RunCommandTool(Workspace(root)).execute(
                    {
                        "command": 'python -c "import time; time.sleep(5)"',
                        "timeout_seconds": 30,
                    },
                    on_output=on_output,
                )
            )

            await asyncio.wait_for(started.wait(), timeout=5)
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task

            meta = [
                event
                for event in events
                if event.get("stream") == "meta"
            ]
            self.assertEqual(meta[-2]["event"], "process_terminating")
            self.assertEqual(meta[-2]["reason"], "user_cancelled")
            self.assertEqual(meta[-1]["event"], "process_terminated")
            self.assertEqual(meta[-1]["reason"], "user_cancelled")


if __name__ == "__main__":
    unittest.main()
