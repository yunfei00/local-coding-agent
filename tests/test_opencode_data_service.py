"""Exercise production data-service admission and real independent worktree verification."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from agent.server.main import AgentServer
from test_agent_reliability import FakeWebSocket


class OpenCodeDataServiceTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        environment = {key:value for key,value in os.environ.items() if not key.startswith("GIT_CONFIG_")}
        env = patch.dict(os.environ, {**environment, "LCA_DATA_DIR": str(root / "data")}, clear=True)
        env.start()
        self.addCleanup(env.stop)
        self.repo = root / "project"
        self.repo.mkdir()
        (self.repo / "value.py").write_text("value = 1\n", encoding="utf-8")
        (self.repo / "test_value.py").write_text(
            "import unittest\nfrom value import value\n"
            "class ProjectTest(unittest.TestCase):\n"
            "    def test_value(self):\n        self.assertEqual(value, 2)\n", encoding="utf-8",
        )
        for args in (["init", "-q", "-b", "main"], ["add", "."],
                     ["-c", "user.name=Fixture", "-c", "user.email=fixture@example.test", "commit", "-qm", "Fixture"]):
            result = subprocess.run(["git", *args], cwd=self.repo, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
        self.server = AgentServer("fixture", data_service=True)
        self.addCleanup(self.server.close)
        self.addAsyncCleanup(self.server.close_async)
        self.project, self.thread, _ = self.server.projects.open(str(self.repo), active_model="fixture")
        self.ws = FakeWebSocket()
        self.server.permissions.set_mode("workspace")

        async def approve(*_args, **_kwargs):
            return "allow_once"
        self.server.approvals.request = approve

    async def request(self, kind, **payload):
        await self.server.handle_message(self.ws, {
            "type":kind, "request_id":"fixture", "thread_id":self.thread.id, "payload":payload,
        }, set())
        return self.ws.messages[-1]

    async def test_desktop_protocol_blocks_old_agent_execution(self):
        for operation in ("turn.start", "turn.append", "task.start", "task.resume", "task.continue", "task.append"):
            result = await self.request(operation, prompt="fixture")
            self.assertEqual(result["payload"]["code"], "OPENCODE_REQUIRED")
        self.assertFalse(self.server.active_turns)
        result = await self.request("turn.record_external", role="assistant", content="OpenCode result", project_id=self.project.id)
        self.assertEqual(result["type"], "turn.recorded")
        self.assertEqual(self.project.state.get_messages(self.thread.id)[-1]["content"], "OpenCode result")

    async def test_open_code_task_keeps_worktree_and_independent_verification(self):
        response = await self.request("task.external.prepare", goal="修复测试",
                                      config={"verification_commands":["python -m unittest discover -v"]})
        self.assertEqual(response["type"], "task.loaded", response.get("payload"))
        task = response["payload"]["task"]
        workspace = Path(task["workspace"])
        self.assertNotEqual(workspace, self.repo)
        self.assertEqual(task["engine"], "opencode")
        self.assertFalse(self.server.active_turns)
        failed = (await self.request("task.external.finish", task_id=task["id"], outcome="succeeded"))["payload"]["task"]
        self.assertEqual(failed["status"], "paused")
        self.assertFalse(failed["verification"][0]["ok"])
        resumed = (await self.request("task.external.prepare", task_id=task["id"], confirm_workspace=True))["payload"]["task"]
        self.assertEqual(resumed["workspace"], str(workspace))
        (workspace / "value.py").write_text("value = 2\n", encoding="utf-8")
        finished = (await self.request("task.external.finish", task_id=task["id"], outcome="succeeded"))["payload"]["task"]
        self.assertEqual(finished["status"], "awaiting_approval", finished)
        self.assertIn("value = 2", finished["report"]["diff"])
        self.assertEqual((self.repo / "value.py").read_text(encoding="utf-8"), "value = 1\n")
