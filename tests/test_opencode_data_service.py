"""Exercise production data-service admission and real independent worktree verification."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from agent.server.main import AgentServer
from test_agent_reliability import FakeWebSocket
from test_m4_diagnostics import CONNECTION, PROFILE


ROOT = Path(__file__).resolve().parent.parent


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

    async def test_online_reservations_enforce_turn_and_global_caps(self):
        response = await self.request("task.catalog.update", catalog={"connections": [CONNECTION], "profiles": [PROFILE]},
                                      config={"budget": {"api_calls": 1, "global_api_calls": 2}})
        self.assertEqual(response["type"], "task.loaded", response)
        payload = {"profile_id": PROFILE["model_profile_id"], "input_bytes": 100, "max_output": 64}
        first = "turn_" + "a" * 32
        self.assertTrue((await self.request("task.external.reserve", turn_id=first, **payload))["payload"]["reserved"])
        denied = await self.request("task.external.reserve", turn_id=first, **payload)
        self.assertIn("api_calls", denied["payload"]["message"])
        second = "turn_" + "b" * 32
        self.assertTrue((await self.request("task.external.reserve", turn_id=second, **payload))["payload"]["reserved"])
        denied = await self.request("task.external.reserve", turn_id="turn_" + "c" * 32, **payload)
        self.assertIn("global_api_calls", denied["payload"]["message"])
        self.assertEqual(self.server.tasks.runtime.usage()["reserved_tokens"], 840)
        self.assertFalse(self.server.tasks.runtime.usage()["actual_cost_known"])

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

    @unittest.skipUnless(sys.platform == "win32", "Requires real Windows desktop APIs")
    async def test_open_code_task_verifies_owned_real_gui_after_repair(self):
        from windows_desktop_support import require_test_desktop
        from test_m4_gui import alive

        require_test_desktop()
        self.server.permissions.set_mode("full_access")
        app = (ROOT / "manual-fixtures/m3-windows-gui/app.ps1").read_text(encoding="utf-8")
        broken = app.replace('Status.Text="Settings ready"', 'Status.Text="Settings broken"')
        self.assertNotEqual(app, broken)
        (self.repo / "app.ps1").write_text(broken, encoding="utf-8")
        (self.repo / "value.py").write_text("value = 2\n", encoding="utf-8")
        (self.repo / ".gitignore").write_text("__pycache__/\n", encoding="utf-8")
        subprocess.run(["git", "add", "."], cwd=self.repo, check=True, capture_output=True)
        subprocess.run(["git", "-c", "user.name=Fixture", "-c", "user.email=fixture@example.test", "commit", "-qm", "GUI fixture"],
                       cwd=self.repo, check=True, capture_output=True)
        state = Path(self.temp.name) / "state.json"
        title = "OpenCode fixture " + self.repo.parent.name
        gui = {"command": f'powershell.exe -NoProfile -STA -File app.ps1 -StatePath "{state}" -Title "{title}"',
               "window_title": title, "timeout_seconds": 90, "steps": [
                   {"tool": "desktop_click", "arguments": {"selector": {"automation_id": "SettingsButton"}}},
                   {"tool": "desktop_wait", "arguments": {"selector": {"automation_id": "StatusLabel"}, "state": "name",
                                                         "expected": "Settings ready", "seconds": 1}},
               ]}
        response = await self.request("task.external.prepare", goal="Fix Settings", config={"gui_verification": gui,
                                      "verification_commands": ["python -m unittest discover -v"]})
        self.assertEqual(response["type"], "task.loaded", response)
        task = response["payload"]["task"]
        failed = (await self.request("task.external.finish", task_id=task["id"], outcome="succeeded"))["payload"]["task"]
        self.assertEqual(failed["status"], "paused", failed)
        self.assertEqual(failed["report"]["gui_verification"], "FAIL", failed)
        self.assertFalse(alive(json.loads(state.read_text(encoding="utf-8-sig"))["pid"]))
        resumed = await self.request("task.external.prepare", task_id=task["id"], confirm_workspace=True)
        self.assertEqual(resumed["payload"]["task"]["workspace"], task["workspace"])
        (Path(task["workspace"]) / "app.ps1").write_text(app, encoding="utf-8")
        finished = (await self.request("task.external.finish", task_id=task["id"], outcome="succeeded"))["payload"]["task"]
        self.assertEqual(finished["status"], "awaiting_approval", finished)
        self.assertEqual(finished["report"]["gui_verification"], "PASS", finished)
        observed = json.loads(state.read_text(encoding="utf-8-sig"))
        self.assertEqual(observed["status"], "Settings ready")
        self.assertFalse(alive(observed["pid"]))
        self.assertEqual((self.repo / "app.ps1").read_text(encoding="utf-8"), broken)
