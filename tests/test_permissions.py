import asyncio
import tempfile
import unittest
from pathlib import Path

from agent.permissions.approval import (
    APPROVAL_ALLOW_ONCE,
    APPROVAL_ALLOW_TURN,
    ApprovalManager,
)
from agent.permissions.policy import (
    PermissionMode,
    PermissionPolicy,
    command_risk,
)
from agent.tools.workspace import Workspace


class PermissionPolicyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.workspace = Workspace(self.temp.name)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_read_only_hides_write_and_shell_tools(self) -> None:
        policy = PermissionPolicy(PermissionMode.READ_ONLY)
        visible = policy.visible_tools(
            [
                "file_exists",
                "read_file",
                "write_file",
                "run_command",
                "git_status",
            ]
        )
        self.assertEqual(visible, ["file_exists", "git_status", "read_file"])

    def test_read_only_denies_write_even_if_called_directly(self) -> None:
        policy = PermissionPolicy(PermissionMode.READ_ONLY)
        verdict = policy.evaluate(
            tool_name="write_file",
            arguments={"path": "a.txt", "content": "x"},
            workspace=self.workspace,
        )
        self.assertFalse(verdict.allowed)
        self.assertEqual(verdict.risk, "read_only")

    def test_workspace_allows_normal_write_inside_workspace(self) -> None:
        policy = PermissionPolicy(PermissionMode.WORKSPACE)
        verdict = policy.evaluate(
            tool_name="write_file",
            arguments={"path": "a.txt", "content": "x"},
            workspace=self.workspace,
            user_prompt="Push this branch to origin.",
        )
        self.assertTrue(verdict.allowed)
        self.assertFalse(verdict.requires_approval)

    def test_workspace_denies_parent_escape(self) -> None:
        policy = PermissionPolicy(PermissionMode.WORKSPACE)
        verdict = policy.evaluate(
            tool_name="read_file",
            arguments={"path": "../outside.txt"},
            workspace=self.workspace,
        )
        self.assertFalse(verdict.allowed)
        self.assertEqual(verdict.risk, "outside_workspace")

    def test_full_access_requires_approval_for_outside_path(self) -> None:
        policy = PermissionPolicy(PermissionMode.FULL_ACCESS)
        outside = str(Path(self.temp.name).parent / "outside.txt")
        verdict = policy.evaluate(
            tool_name="read_file",
            arguments={"path": outside},
            workspace=self.workspace,
        )
        self.assertTrue(verdict.allowed)
        self.assertTrue(verdict.requires_approval)
        self.assertEqual(verdict.risk, "outside_workspace")

    def test_risky_git_push_requires_approval(self) -> None:
        policy = PermissionPolicy(PermissionMode.WORKSPACE)
        verdict = policy.evaluate(
            tool_name="run_command",
            arguments={"command": "git push origin main"},
            workspace=self.workspace,
        )
        self.assertTrue(verdict.allowed)
        self.assertTrue(verdict.requires_approval)
        self.assertEqual(verdict.risk, "git_publish")

    def test_read_only_allows_only_trusted_read_only_mcp(self) -> None:
        policy = PermissionPolicy(PermissionMode.READ_ONLY)
        metadata = {
            "mcp__docs__read": {
                "source": "mcp",
                "server": "docs",
                "trusted": True,
                "read_only": True,
                "risk": "mcp_read_only",
            },
            "mcp__docs__write": {
                "source": "mcp",
                "server": "docs",
                "trusted": True,
                "read_only": False,
                "risk": "mcp_mutating",
            },
        }
        visible = policy.visible_tools(
            ["read_file", "mcp__docs__read", "mcp__docs__write"],
            metadata,
        )
        self.assertEqual(
            visible,
            ["mcp__docs__read", "read_file"],
        )

        allowed = policy.evaluate(
            tool_name="mcp__docs__read",
            arguments={"id": "1"},
            workspace=self.workspace,
            tool_metadata=metadata["mcp__docs__read"],
        )
        denied = policy.evaluate(
            tool_name="mcp__docs__write",
            arguments={"id": "1"},
            workspace=self.workspace,
            tool_metadata=metadata["mcp__docs__write"],
        )
        self.assertTrue(allowed.allowed)
        self.assertFalse(allowed.requires_approval)
        self.assertFalse(denied.allowed)
        self.assertEqual(denied.risk, "read_only")

    def test_workspace_requires_approval_for_untrusted_or_mutating_mcp(self) -> None:
        policy = PermissionPolicy(PermissionMode.WORKSPACE)
        verdict = policy.evaluate(
            tool_name="mcp__remote__update",
            arguments={"value": "x"},
            workspace=self.workspace,
            tool_metadata={
                "source": "mcp",
                "server": "remote",
                "trusted": False,
                "read_only": False,
                "risk": "mcp_mutating",
            },
        )
        self.assertTrue(verdict.allowed)
        self.assertTrue(verdict.requires_approval)
        self.assertEqual(verdict.risk, "mcp_mutating")

    def test_mcp_git_push_keeps_publish_risk(self) -> None:
        policy = PermissionPolicy(PermissionMode.WORKSPACE)
        verdict = policy.evaluate(
            tool_name="mcp__git__push",
            arguments={"branch": "main"},
            workspace=self.workspace,
            tool_metadata={
                "source": "mcp",
                "server": "git",
                "trusted": True,
                "read_only": False,
                "risk": "git_publish",
            },
            user_prompt="Please push this branch.",
        )
        self.assertTrue(verdict.allowed)
        self.assertTrue(verdict.requires_approval)
        self.assertEqual(verdict.risk, "git_publish")

    def test_git_commit_requires_current_user_intent(self) -> None:
        policy = PermissionPolicy(PermissionMode.WORKSPACE)
        denied = policy.evaluate(
            tool_name="git_commit",
            arguments={"message": "update"},
            workspace=self.workspace,
            user_prompt="Run the tests and fix any failures.",
        )
        allowed = policy.evaluate(
            tool_name="git_commit",
            arguments={"message": "update"},
            workspace=self.workspace,
            user_prompt="Commit these changes with a suitable message.",
        )
        self.assertFalse(denied.allowed)
        self.assertEqual(denied.risk, "git_commit_intent")
        self.assertTrue(allowed.allowed)
        self.assertTrue(allowed.requires_approval)
        self.assertEqual(allowed.risk, "git_commit")

    def test_worktree_requires_current_user_intent(self) -> None:
        policy = PermissionPolicy(PermissionMode.WORKSPACE)
        denied = policy.evaluate(
            tool_name="git_worktree_create",
            arguments={"task_name": "demo", "branch": "demo/task"},
            workspace=self.workspace,
            user_prompt="Inspect the repository.",
        )
        allowed = policy.evaluate(
            tool_name="git_worktree_create",
            arguments={"task_name": "demo", "branch": "demo/task"},
            workspace=self.workspace,
            user_prompt="Create an isolated worktree for this task.",
        )
        self.assertFalse(denied.allowed)
        self.assertEqual(denied.risk, "git_worktree_intent")
        self.assertTrue(allowed.allowed)
        self.assertTrue(allowed.requires_approval)

    def test_mcp_git_publish_requires_current_user_intent(self) -> None:
        policy = PermissionPolicy(PermissionMode.WORKSPACE)
        denied = policy.evaluate(
            tool_name="mcp__git__push",
            arguments={"branch": "main"},
            workspace=self.workspace,
            tool_metadata={
                "source": "mcp",
                "server": "git",
                "trusted": True,
                "read_only": False,
                "risk": "git_publish",
            },
            user_prompt="Inspect the current branch.",
        )
        self.assertFalse(denied.allowed)
        self.assertEqual(denied.risk, "git_publish_intent")

    def test_safe_test_command_does_not_require_approval(self) -> None:
        policy = PermissionPolicy(PermissionMode.WORKSPACE)
        verdict = policy.evaluate(
            tool_name="run_command",
            arguments={"command": "python -m unittest"},
            workspace=self.workspace,
        )
        self.assertTrue(verdict.allowed)
        self.assertFalse(verdict.requires_approval)

    def test_command_risk_detects_destructive_git(self) -> None:
        risk = command_risk("git reset --hard HEAD")
        self.assertIsNotNone(risk)
        self.assertEqual(risk[0], "git_destructive")

    def test_workspace_runtime_guard_and_full_access_toggle(self) -> None:
        outside = Path(self.temp.name).parent / "outside.txt"
        with self.assertRaises(Exception):
            self.workspace.resolve(outside, must_exist=False)

        self.workspace.set_full_access(True)
        resolved = self.workspace.resolve(outside, must_exist=False)
        self.assertEqual(resolved, outside.resolve(strict=False))


class FakeWebSocket:
    def __init__(self) -> None:
        self.messages = []

    async def send_json(self, payload) -> None:
        self.messages.append(payload)


class ApprovalManagerTests(unittest.IsolatedAsyncioTestCase):
    async def test_allow_once_resolves_pending_request(self) -> None:
        manager = ApprovalManager()
        ws = FakeWebSocket()

        task = asyncio.create_task(
            manager.request(
                ws,
                turn_id="turn_1",
                thread_id="thread_1",
                approval_key="key_1",
                tool_name="run_command",
                arguments={"command": "git push"},
                reason="publish",
                risk="git_publish",
            )
        )
        await asyncio.sleep(0)

        approval_id = ws.messages[0]["payload"]["approval_id"]
        manager.respond(approval_id, APPROVAL_ALLOW_ONCE)
        decision = await task

        self.assertEqual(decision, APPROVAL_ALLOW_ONCE)
        self.assertFalse(manager.is_granted_for_turn("turn_1", "key_1"))

    async def test_allow_turn_caches_grant(self) -> None:
        manager = ApprovalManager()
        ws = FakeWebSocket()

        task = asyncio.create_task(
            manager.request(
                ws,
                turn_id="turn_2",
                thread_id="thread_2",
                approval_key="key_2",
                tool_name="run_command",
                arguments={"command": "git push"},
                reason="publish",
                risk="git_publish",
            )
        )
        await asyncio.sleep(0)

        approval_id = ws.messages[0]["payload"]["approval_id"]
        manager.respond(approval_id, APPROVAL_ALLOW_TURN)
        decision = await task

        self.assertEqual(decision, APPROVAL_ALLOW_TURN)
        self.assertTrue(manager.is_granted_for_turn("turn_2", "key_2"))

        manager.finish_turn("turn_2")
        self.assertFalse(manager.is_granted_for_turn("turn_2", "key_2"))


if __name__ == "__main__":
    unittest.main()
