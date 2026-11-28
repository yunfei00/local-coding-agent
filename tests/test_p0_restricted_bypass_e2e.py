import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
try:
    import test_unified_runtime as fixture
except ModuleNotFoundError:
    import tests.test_unified_runtime as fixture  # type: ignore

from agent.llm.base import ToolCall
from agent.permissions.policy import PermissionMode


class RestrictedBypassE2ETests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = fixture.UnifiedLoopTests.asyncSetUp
    asyncTearDown = fixture.UnifiedLoopTests.asyncTearDown

    async def _call(self, name, args):
        return await self.server._authorize_tool(
            self.ws,
            project=self.project,
            call=ToolCall(name, args),
            call_id="p0:" + name,
            thread_id=self.thread.id,
            turn_id="p0-restricted",
            user_prompt="test restricted bypass",
        )

    async def test_restricted_blocks_mutating_tools_at_execution_entry(self):
        self.server.authorizations.configure("restricted")
        self.assertEqual(self.server.authorizations.effective(self.project.id).mode, PermissionMode.RESTRICTED)

        cases = [
            ("run_command", {"command": "echo bypass"}),
            ("write_file", {"path": "x.txt", "content": "x"}),
            ("delete_file", {"path": "x.txt"}),
            ("git_commit", {"message": "x"}),
            ("git_stage", {"paths": ["x.txt"]}),
            ("start_process", {"command": "python -V"}),
        ]
        for name, args in cases:
            with self.subTest(tool=name):
                r = await self._call(name, args)
                self.assertFalse(r.get("ok"), name)
                self.assertEqual(r.get("error", {}).get("code"), "PERMISSION_DENIED", name)

        # read-only allowed
        r = await self._call("list_directory", {"path": "."})
        self.assertTrue(r.get("ok"))


if __name__ == "__main__":
    unittest.main()
