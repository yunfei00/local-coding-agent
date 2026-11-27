from __future__ import annotations

import unittest

from agent.permissions.policy import PermissionMode, PermissionPolicy
from agent.tools.workspace import Workspace


class P0PermissionMatrixTests(unittest.TestCase):
    def setUp(self):
        import tempfile, pathlib
        self.tmp = tempfile.TemporaryDirectory()
        self.ws = Workspace(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_restricted_blocks_shell_write_and_mcp(self):
        p = PermissionPolicy(PermissionMode.RESTRICTED)
        v = p.evaluate(tool_name="run_command", arguments={"command": "echo hi"}, workspace=self.ws)
        self.assertFalse(v.allowed)
        self.assertEqual(v.risk, "restricted")
        v = p.evaluate(tool_name="write_file", arguments={"path": "a.txt", "content": "x"}, workspace=self.ws)
        self.assertFalse(v.allowed)
        v = p.evaluate(tool_name="mcp__s__tool", arguments={}, workspace=self.ws, tool_metadata={"source": "mcp", "server": "s", "trusted": True, "read_only": True, "risk": "mcp_read_only"})
        self.assertFalse(v.allowed)  # default deny unless override allow

    def test_restricted_allows_readonly_whitelist(self):
        p = PermissionPolicy(PermissionMode.RESTRICTED)
        v = p.evaluate(tool_name="read_file", arguments={"path": "."}, workspace=self.ws)
        self.assertTrue(v.allowed)
        v = p.evaluate(tool_name="git_status", arguments={}, workspace=self.ws)
        self.assertTrue(v.allowed)

    def test_restricted_mcp_explicit_allow_only(self):
        p = PermissionPolicy(PermissionMode.RESTRICTED)
        meta = {"source": "mcp", "server": "s", "trusted": True, "read_only": True, "risk": "mcp_read_only", "permission_override": "allow"}
        v = p.evaluate(tool_name="mcp__s__t", arguments={}, workspace=self.ws, tool_metadata=meta)
        self.assertTrue(v.allowed)
        meta["permission_override"] = "ask"
        v = p.evaluate(tool_name="mcp__s__t", arguments={}, workspace=self.ws, tool_metadata=meta)
        self.assertFalse(v.allowed)

    def test_mcp_override_deny_allow_ask(self):
        p = PermissionPolicy(PermissionMode.WORKSPACE)
        meta = {"source": "mcp", "server": "s", "trusted": False, "read_only": False, "risk": "mcp_mutating", "permission_override": "deny"}
        v = p.evaluate(tool_name="mcp__s__t", arguments={}, workspace=self.ws, tool_metadata=meta)
        self.assertFalse(v.allowed)
        meta["permission_override"] = "allow"
        v = p.evaluate(tool_name="mcp__s__t", arguments={}, workspace=self.ws, tool_metadata=meta)
        self.assertTrue(v.allowed)
        self.assertFalse(v.requires_approval)
        meta["permission_override"] = "ask"
        v = p.evaluate(tool_name="mcp__s__t", arguments={}, workspace=self.ws, tool_metadata=meta)
        self.assertTrue(v.allowed)
        self.assertTrue(v.requires_approval)

    def test_approval_mode_requires_confirmation_for_mutation(self):
        p = PermissionPolicy(PermissionMode.APPROVAL)
        v = p.evaluate(tool_name="write_file", arguments={"path": "a.txt", "content": "x"}, workspace=self.ws)
        self.assertTrue(v.allowed)
        self.assertTrue(v.requires_approval)
        v = p.evaluate(tool_name="read_file", arguments={"path": "."}, workspace=self.ws)
        self.assertTrue(v.allowed)
        self.assertFalse(v.requires_approval)

    def test_restricted_blocks_network_like_shell(self):
        p = PermissionPolicy(PermissionMode.RESTRICTED)
        for cmd in ["curl http://example.com", "wget http://example.com", "Invoke-WebRequest http://x"]:
            v = p.evaluate(tool_name="run_command", arguments={"command": cmd}, workspace=self.ws)
            self.assertFalse(v.allowed, cmd)

    def test_restricted_blocks_git_write(self):
        p = PermissionPolicy(PermissionMode.RESTRICTED)
        v = p.evaluate(tool_name="git_commit", arguments={"message": "x"}, workspace=self.ws)
        self.assertFalse(v.allowed)
        v = p.evaluate(tool_name="git_stage", arguments={"paths": ["a"]}, workspace=self.ws)
        self.assertFalse(v.allowed)

    def test_outside_workspace_requires_approval(self):
        p = PermissionPolicy(PermissionMode.WORKSPACE)
        v = p.evaluate(tool_name="write_file", arguments={"path": "C:/Windows/temp/a.txt", "content": "x"}, workspace=self.ws)
        self.assertTrue(v.allowed)
        self.assertTrue(v.requires_approval)
        self.assertEqual(v.risk, "outside_workspace")

    def test_restricted_denies_outside_workspace(self):
        p = PermissionPolicy(PermissionMode.RESTRICTED)
        v = p.evaluate(tool_name="read_file", arguments={"path": "C:/Windows/temp/a.txt"}, workspace=self.ws)
        # RESTRICTED allows read_file by tool whitelist but path outside workspace still must be guarded
        self.assertTrue(v.requires_approval or not v.allowed)

    def test_full_access_still_gates_high_risk_git(self):
        p = PermissionPolicy(PermissionMode.FULL_ACCESS)
        v = p.evaluate(tool_name="git_commit", arguments={"message": "x"}, workspace=self.ws, user_prompt="fix bug")
        self.assertFalse(v.allowed)  # explicit intent required

    def test_restricted_blocks_common_bypass_tools(self):
        p = PermissionPolicy(PermissionMode.RESTRICTED)
        cases = [
            ("start_process", {"command": "python -c print(1)"}),
            ("delete_file", {"path": "a.txt"}),
            ("apply_patch", {"path": "a.txt", "patch": "*** Begin Patch\n*** End Patch"}),
            ("environment_repair", {"action": "project_npm_proxy_reset"}),
            ("git_stage", {"paths": ["a.txt"]}),
            ("git_unstage", {"paths": ["a.txt"]}),
        ]
        for name, args in cases:
            v = p.evaluate(tool_name=name, arguments=args, workspace=self.ws)
            self.assertFalse(v.allowed, name)

    def test_restricted_blocks_desktop_tools(self):
        p = PermissionPolicy(PermissionMode.RESTRICTED)
        for name in ["desktop_screenshot", "desktop_click", "desktop_type_text", "desktop_list_windows"]:
            v = p.evaluate(tool_name=name, arguments={"window_id": "w1"}, workspace=self.ws)
            self.assertFalse(v.allowed, name)

    def test_restricted_blocks_unknown_tool(self):
        p = PermissionPolicy(PermissionMode.RESTRICTED)
        v = p.evaluate(tool_name="totally_unknown_tool", arguments={}, workspace=self.ws)
        self.assertFalse(v.allowed)


if __name__ == "__main__":
    unittest.main()
