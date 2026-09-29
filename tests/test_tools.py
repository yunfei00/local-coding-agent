import asyncio
import tempfile
import unittest
from pathlib import Path

from agent.tools.base import ToolError
from agent.tools.filesystem import (
    ApplyPatchTool,
    ReadFileTool,
    SearchFilesTool,
    WriteFileTool,
)
from agent.tools.registry import ToolRegistry
from agent.tools.shell import RunCommandTool, validate_command
from agent.tools.workspace import Workspace


class WorkspaceTests(unittest.TestCase):
    def test_rejects_path_outside_workspace(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            workspace = Workspace(root)
            outside = Path(root).parent / "outside.txt"
            with self.assertRaises(ToolError) as ctx:
                workspace.resolve(outside)
            self.assertEqual(ctx.exception.code, "PATH_OUTSIDE_WORKSPACE")

    def test_registry_contains_phase3_tools(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            names = ToolRegistry(Workspace(root)).names
            self.assertEqual(
                names,
                [
                    "apply_patch",
                    "git_diff",
                    "git_log",
                    "git_status",
                    "list_directory",
                    "read_file",
                    "run_command",
                    "search_files",
                    "write_file",
                ],
            )


class FileToolTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.workspace = Workspace(self.temp.name)

    async def asyncTearDown(self) -> None:
        self.temp.cleanup()

    async def test_write_read_patch_and_search(self) -> None:
        write = WriteFileTool(self.workspace)
        read = ReadFileTool(self.workspace)
        patch = ApplyPatchTool(self.workspace)
        search = SearchFilesTool(self.workspace)

        result = await write.execute(
            {"path": "src/demo.py", "content": "VALUE = 1\nprint(VALUE)\n"}
        )
        self.assertTrue(result.ok)
        self.assertEqual(result.changed_paths, ["src/demo.py"])

        read_result = await read.execute({"path": "src/demo.py"})
        self.assertIn("VALUE = 1", read_result.data["content"])

        patch_result = await patch.execute(
            {
                "path": "src/demo.py",
                "old_text": "VALUE = 1",
                "new_text": "VALUE = 2",
            }
        )
        self.assertTrue(patch_result.ok)

        search_result = await search.execute(
            {"query": "VALUE = 2", "glob": "*.py"}
        )
        self.assertEqual(search_result.data["results"][0]["path"], "src/demo.py")

    async def test_patch_rejects_ambiguous_text(self) -> None:
        path = Path(self.temp.name) / "a.txt"
        path.write_text("x\nx\n", encoding="utf-8")
        patch = ApplyPatchTool(self.workspace)

        with self.assertRaises(ToolError) as ctx:
            await patch.execute(
                {"path": "a.txt", "old_text": "x", "new_text": "y"}
            )
        self.assertEqual(ctx.exception.code, "PATCH_AMBIGUOUS")


class ShellToolTests(unittest.IsolatedAsyncioTestCase):
    def test_blocks_destructive_command(self) -> None:
        with self.assertRaises(ToolError) as ctx:
            validate_command("git reset --hard HEAD")
        self.assertEqual(ctx.exception.code, "COMMAND_BLOCKED")

    async def test_runs_safe_command(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            tool = RunCommandTool(Workspace(root))
            result = await tool.execute(
                {"command": "git --version", "timeout_seconds": 30}
            )
            self.assertTrue(result.ok)
            self.assertIn("git version", result.stdout.lower())


if __name__ == "__main__":
    unittest.main()
