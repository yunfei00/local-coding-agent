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
        v = p.evaluate(tool_name="run_command", arguments={"command":"echo hi"}, workspace=self.ws)
        self.assertFalse(v.allowed)
        self.assertEqual(v.risk, "restricted")
        v = p.evaluate(tool_name="write_file", arguments={"path":"a.txt","content":"x"}, workspace=self.ws)
        self.assertFalse(v.allowed)
        v = p.evaluate(tool_name="mcp__s__tool", arguments={}, workspace=self.ws, tool_metadata={"source":"mcp","server":"s","trusted":True,"read_only":True,"risk":"mcp_read_only"})
        self.assertFalse(v.allowed)  # default deny unless override allow

    def test_restricted_allows_readonly_whitelist(self):
        p = PermissionPolicy(PermissionMode.RESTRICTED)
        v = p.evaluate(tool_name="read_file", arguments={"path":"."}, workspace=self.ws)
        self.assertTrue(v.allowed)
        v = p.evaluate(tool_name="git_status", arguments={}, workspace=self.ws)
        self.assertTrue(v.allowed)

    def test_mcp_override_deny_allow_ask(self):
        p = PermissionPolicy(PermissionMode.WORKSPACE)
        meta = {"source":"mcp","server":"s","trusted":False,"read_only":False,"risk":"mcp_mutating","permission_override":"deny"}
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
        v = p.evaluate(tool_name="write_file", arguments={"path":"a.txt","content":"x"}, workspace=self.ws)
        self.assertTrue(v.allowed)
        self.assertTrue(v.requires_approval)
        v = p.evaluate(tool_name="read_file", arguments={"path":"."}, workspace=self.ws)
        self.assertTrue(v.allowed)
        self.assertFalse(v.requires_approval)


if __name__ == "__main__":
    unittest.main()
