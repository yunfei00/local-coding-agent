import asyncio
import subprocess
import tempfile
import time
import unittest
from pathlib import Path

from agent.tools.diff import parse_unified_diff
from agent.tools.git import GitDiffTool
from agent.tools.shell import RunCommandTool
from agent.tools.workspace import Workspace


SAMPLE_DIFF = """diff --git a/demo.py b/demo.py
index 1234567..7654321 100644
--- a/demo.py
+++ b/demo.py
@@ -1,2 +1,2 @@
-value = 1
+value = 2
 print(value)
"""


class DiffParserTests(unittest.TestCase):
    def test_parse_unified_diff_with_line_numbers(self) -> None:
        files = parse_unified_diff(SAMPLE_DIFF)
        self.assertEqual(len(files), 1)
        file = files[0]
        self.assertEqual(file["path"], "demo.py")
        self.assertEqual(file["additions"], 1)
        self.assertEqual(file["deletions"], 1)

        lines = file["hunks"][0]["lines"]
        self.assertEqual(lines[0]["type"], "delete")
        self.assertEqual(lines[0]["old_line"], 1)
        self.assertIsNone(lines[0]["new_line"])
        self.assertEqual(lines[1]["type"], "add")
        self.assertEqual(lines[1]["new_line"], 1)


class GitDiffToolTests(unittest.IsolatedAsyncioTestCase):
    async def test_diff_includes_tracked_and_untracked_files(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            repo = Path(root)
            subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
            subprocess.run(
                ["git", "config", "user.email", "ci@example.test"],
                cwd=repo,
                check=True,
            )
            subprocess.run(
                ["git", "config", "user.name", "CI"],
                cwd=repo,
                check=True,
            )

            tracked = repo / "tracked.txt"
            tracked.write_text("old\n", encoding="utf-8")
            subprocess.run(["git", "add", "tracked.txt"], cwd=repo, check=True)
            subprocess.run(
                ["git", "commit", "-q", "-m", "initial"],
                cwd=repo,
                check=True,
            )

            tracked.write_text("new\n", encoding="utf-8")
            (repo / "new.txt").write_text(
                "first\nsecond\n",
                encoding="utf-8",
            )
            cache_dir = repo / "__pycache__"
            cache_dir.mkdir()
            (cache_dir / "noise.pyc").write_bytes(b"noise")

            result = await GitDiffTool(Workspace(repo)).execute({})
            self.assertTrue(result.ok)

            files = result.data["files"]
            by_path = {item["path"]: item for item in files}

            self.assertIn("tracked.txt", by_path)
            self.assertIn("new.txt", by_path)
            self.assertNotIn("__pycache__/noise.pyc", by_path)
            self.assertEqual(by_path["new.txt"]["status"], "untracked")
            self.assertEqual(by_path["new.txt"]["additions"], 2)


class CommandCancellationTests(unittest.IsolatedAsyncioTestCase):
    async def test_cancelling_command_returns_quickly(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            tool = RunCommandTool(Workspace(root))
            started = asyncio.Event()

            async def on_output(chunk) -> None:
                if (
                    chunk.get("stream") == "meta"
                    and chunk.get("event") == "process_started"
                ):
                    started.set()

            command = (
                'python -c "import subprocess,sys,time; '
                "subprocess.Popen([sys.executable,'-c','import time; time.sleep(5)']); "
                'time.sleep(5)"'
            )

            task = asyncio.create_task(
                tool.execute(
                    {
                        "command": command,
                        "timeout_seconds": 30,
                    },
                    on_output=on_output,
                )
            )

            await asyncio.wait_for(started.wait(), timeout=5)
            began_cancel = time.perf_counter()
            task.cancel()

            with self.assertRaises(asyncio.CancelledError):
                await task

            self.assertLess(time.perf_counter() - began_cancel, 4.0)


if __name__ == "__main__":
    unittest.main()
