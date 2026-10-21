from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from agent.tools.base import ToolError
from agent.tools.git import (
    GitCommitTool,
    GitStageTool,
    GitUnstageTool,
    GitWorktreeCreateTool,
    GitWorktreeRemoveTool,
    _validated_branch,
    _worktree_records,
)
from agent.tools.workspace import Workspace


class _FakeProcess:
    def __init__(
        self,
        stdout: bytes,
        stderr: bytes = b"",
        returncode: int = 0,
    ) -> None:
        self._stdout = stdout
        self._stderr = stderr
        self.returncode = returncode

    async def communicate(self):
        return self._stdout, self._stderr

    def kill(self) -> None:
        return None

    async def wait(self) -> int:
        return self.returncode


class GitWorkflowV3Tests(unittest.IsolatedAsyncioTestCase):
    def test_branch_validation(self) -> None:
        self.assertEqual(
            _validated_branch("phase25/task-worktree"),
            "phase25/task-worktree",
        )
        for value in ("", "../bad", "/bad", "bad..name", "bad@{ref"):
            with self.assertRaises(ToolError):
                _validated_branch(value)

    async def test_stage_and_unstage_use_structured_tools(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            workspace = Workspace(root)
            status = {
                "branch": "main",
                "staged": ["src/app.py"],
                "unstaged": [],
                "untracked": [],
                "staged_count": 1,
                "unstaged_count": 0,
                "untracked_count": 0,
                "clean": False,
            }
            git_mock = AsyncMock(return_value=(0, "", ""))
            status_mock = AsyncMock(return_value=status)
            with (
                patch("agent.tools.git._git", git_mock),
                patch(
                    "agent.tools.git._structured_status",
                    status_mock,
                ),
            ):
                staged = await GitStageTool(workspace).execute(
                    {"paths": ["src/app.py"]}
                )
                self.assertTrue(staged.ok)
                self.assertEqual(staged.data["staged_count"], 1)
                self.assertEqual(
                    git_mock.await_args.args[1:],
                    ("add", "--", "src/app.py"),
                )

                git_mock.reset_mock()
                unstaged_status = {
                    **status,
                    "staged": [],
                    "staged_count": 0,
                    "unstaged": ["src/app.py"],
                    "unstaged_count": 1,
                }
                status_mock.return_value = unstaged_status
                unstaged = await GitUnstageTool(workspace).execute(
                    {"paths": ["src/app.py"]}
                )
                self.assertTrue(unstaged.ok)
                self.assertEqual(
                    git_mock.await_args.args[1:],
                    ("restore", "--staged", "--", "src/app.py"),
                )

    async def test_commit_requires_staged_content(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            workspace = Workspace(root)
            empty_status = {
                "branch": "main",
                "staged": [],
                "unstaged": [],
                "untracked": [],
                "staged_count": 0,
                "unstaged_count": 0,
                "untracked_count": 0,
                "clean": True,
            }
            with patch(
                "agent.tools.git._structured_status",
                AsyncMock(return_value=empty_status),
            ):
                with self.assertRaises(ToolError) as ctx:
                    await GitCommitTool(workspace).execute(
                        {"message": "should not happen"}
                    )
                self.assertEqual(ctx.exception.code, "GIT_NOTHING_STAGED")

    async def test_commit_executes_only_after_tool_is_called(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            workspace = Workspace(root)
            before = {
                "branch": "main",
                "staged": ["src/app.py"],
                "unstaged": [],
                "untracked": [],
                "staged_count": 1,
                "unstaged_count": 0,
                "untracked_count": 0,
                "clean": False,
            }
            after = {
                **before,
                "staged": [],
                "staged_count": 0,
                "clean": True,
            }
            git_mock = AsyncMock(
                return_value=(0, "[main abc123] phase25", "")
            )
            status_mock = AsyncMock(side_effect=[before, after])
            with (
                patch("agent.tools.git._git", git_mock),
                patch(
                    "agent.tools.git._structured_status",
                    status_mock,
                ),
            ):
                result = await GitCommitTool(workspace).execute(
                    {"message": "phase25 explicit commit"}
                )
                self.assertTrue(result.ok)
                self.assertEqual(
                    git_mock.await_args.args[1:],
                    ("commit", "-m", "phase25 explicit commit"),
                )

    async def test_worktree_porcelain_marks_managed_storage(self) -> None:
        with (
            tempfile.TemporaryDirectory() as root,
            tempfile.TemporaryDirectory() as data_root,
            patch.dict(
                os.environ,
                {"LCA_DATA_DIR": data_root},
                clear=False,
            ),
        ):
            workspace = Workspace(root)
            managed = (
                Path(data_root)
                / "worktrees"
                / "repo"
                / "phase25-isolated"
            )
            porcelain = (
                f"worktree {Path(root).resolve()}\n"
                "HEAD aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa\n"
                "branch refs/heads/main\n\n"
                f"worktree {managed}\n"
                "HEAD bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb\n"
                "branch refs/heads/phase25/task-worktree\n\n"
            )
            with patch(
                "agent.tools.git._git",
                AsyncMock(return_value=(0, porcelain, "")),
            ):
                records = await _worktree_records(workspace)

            self.assertEqual(len(records), 2)
            self.assertTrue(records[0]["current"])
            self.assertFalse(records[0]["managed"])
            self.assertTrue(records[1]["managed"])
            self.assertEqual(
                records[1]["branch"],
                "phase25/task-worktree",
            )

    async def test_worktree_create_uses_managed_path(self) -> None:
        with (
            tempfile.TemporaryDirectory() as root,
            tempfile.TemporaryDirectory() as data_root,
            patch.dict(
                os.environ,
                {"LCA_DATA_DIR": data_root},
                clear=False,
            ),
        ):
            workspace = Workspace(root)
            git_mock = AsyncMock(return_value=(0, "Preparing worktree", ""))
            with (
                patch("agent.tools.git._git", git_mock),
                patch(
                    "agent.tools.git._worktree_records",
                    AsyncMock(return_value=[]),
                ),
            ):
                result = await GitWorktreeCreateTool(workspace).execute(
                    {
                        "task_name": "phase25-isolated",
                        "branch": "phase25/task-worktree",
                        "base_ref": "HEAD",
                    }
                )

            self.assertTrue(result.ok)
            target = Path(result.data["path"])
            self.assertTrue(
                str(target).startswith(
                    str((Path(data_root) / "worktrees").resolve())
                )
            )
            args = git_mock.await_args.args[1:]
            self.assertEqual(args[:3], ("worktree", "add", "-b"))
            self.assertEqual(args[3], "phase25/task-worktree")
            self.assertEqual(Path(args[4]), target)
            self.assertEqual(args[5], "HEAD")

    async def test_dirty_worktree_remove_is_refused(self) -> None:
        with (
            tempfile.TemporaryDirectory() as root,
            tempfile.TemporaryDirectory() as data_root,
            patch.dict(
                os.environ,
                {"LCA_DATA_DIR": data_root},
                clear=False,
            ),
        ):
            workspace = Workspace(root)
            managed_root = (
                Path(data_root)
                / "worktrees"
                / __import__("hashlib").sha256(
                    str(workspace.root).encode("utf-8")
                ).hexdigest()[:12]
            )
            target = managed_root / "phase25-isolated"
            target.mkdir(parents=True)

            process = _FakeProcess(b" M src/app.py\n")
            with patch(
                "agent.tools.git.asyncio.create_subprocess_exec",
                AsyncMock(return_value=process),
            ):
                with self.assertRaises(ToolError) as ctx:
                    await GitWorktreeRemoveTool(workspace).execute(
                        {"path": str(target)}
                    )
            self.assertEqual(ctx.exception.code, "WORKTREE_DIRTY")


if __name__ == "__main__":
    unittest.main()
