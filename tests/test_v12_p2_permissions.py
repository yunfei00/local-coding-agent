import tempfile
import unittest
from agent.permissions.policy import PermissionPolicy,PermissionMode
from agent.tools.workspace import Workspace

class P2PermissionTests(unittest.TestCase):
    def test_tool_visibility(self):
        with tempfile.TemporaryDirectory() as d:
            names=["skills_list","skills_read","skills_suggest","office_document","browser_snapshot","browser_session"]
            self.assertEqual(PermissionPolicy(PermissionMode.READ_ONLY).visible_tools(names),
                             ["browser_snapshot","skills_list","skills_read","skills_suggest"])
            workspace_visible=PermissionPolicy(PermissionMode.WORKSPACE).visible_tools(names)
            self.assertIn("browser_session",workspace_visible)
            self.assertIn("office_document",workspace_visible)

    def test_interactive_actions_require_fresh_approval(self):
        with tempfile.TemporaryDirectory() as d:
            workspace=Workspace(d)
            policy=PermissionPolicy(PermissionMode.FULL_ACCESS,continuous=True)
            for tool,operation in [("browser_session","click"),("browser_session","workflow"),
                                   ("office_document","edit"),("office_document","export_pdf")]:
                verdict=policy.evaluate(tool_name=tool,arguments={"operation":operation,"path":"report.xlsx"},
                                        workspace=workspace)
                self.assertTrue(verdict.allowed)
                self.assertTrue(verdict.requires_approval)
                self.assertTrue(verdict.approval_key)

    def test_read_only_tools_are_not_blocked(self):
        with tempfile.TemporaryDirectory() as d:
            workspace=Workspace(d)
            policy=PermissionPolicy(PermissionMode.WORKSPACE)
            for tool,operation in [("browser_session","snapshot"),("office_document","inspect")]:
                verdict=policy.evaluate(tool_name=tool,arguments={"operation":operation},workspace=workspace)
                self.assertTrue(verdict.allowed)
                self.assertFalse(verdict.requires_approval)

if __name__=="__main__":
    unittest.main()
