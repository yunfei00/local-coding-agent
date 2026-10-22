"""Actual directory creation, existing-data protection and project/thread persistence."""
import asyncio
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch, AsyncMock

from agent.server.main import AgentServer
from agent.server.projects import create_project_folder
from agent.tools.base import ToolError
from test_agent_reliability import FakeWebSocket


class ProjectCreationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.env = patch.dict(os.environ, {"LCA_DATA_DIR":str(self.root / "data")})
        self.env.start()
        self.server = AgentServer("test")
        self.ws = FakeWebSocket()

    async def asyncTearDown(self):
        await self.server.close_async()
        self.server.close()
        self.env.stop()
        self.temp.cleanup()

    async def create(self, **options):
        await self.server.handle_message(self.ws, {"type":"project.create", "payload":{
            "parent_path":str(self.root), "name":"新工程", "initialize_git":True, **options}}, set())
        return self.ws.messages[-1]

    async def test_create_initializes_git_without_committing_and_uses_existing_registry(self):
        event = await self.create()
        self.assertEqual(event["type"],"project.opened",event)
        folder = self.root / "新工程"
        self.assertTrue((folder / ".git").is_dir())
        self.assertEqual(self.server.projects.active.workspace.root, folder.resolve())
        self.assertEqual(len(self.server.projects.active.state.list_threads()),1)
        self.assertNotEqual(subprocess.run(["git","rev-parse","--verify","HEAD"],cwd=folder,capture_output=True).returncode,0)
        self.assertTrue(self.server.store.list_projects())

    async def test_plain_folder_creation_does_not_require_git(self):
        with patch("agent.tools.git._git",new_callable=AsyncMock) as git:
            event = await self.create(initialize_git=False)
            git.assert_not_called()
        self.assertEqual(event["type"],"project.opened")
        self.assertEqual(list((self.root / "新工程").iterdir()),[])

    async def test_existing_directory_and_files_are_never_overwritten(self):
        target = self.root / "existing"
        target.mkdir()
        (target / "user.txt").write_text("keep",encoding="utf-8")
        event = await self.create(name="existing")
        self.assertEqual(event["type"],"error")
        self.assertEqual((target / "user.txt").read_text(),"keep")
        self.assertFalse((target / ".git").exists())
        self.assertIsNone(self.server.projects.active)
        (self.root / "file.txt").write_text("keep")
        self.assertEqual((await self.create(name="file.txt"))["type"],"error")
        self.assertEqual((self.root / "file.txt").read_text(),"keep")

    async def test_invalid_names_and_locations_make_no_directories(self):
        for name in ("", ".", "..", "../escape", "nested/path", "nested\\path", "CON", "nul.txt", "LPT1", "trailing.", " padded", "a:b", "a\nnew", "a"*101):
            with self.subTest(name=name), self.assertRaises(ToolError):
                create_project_folder(str(self.root),name)
        with self.assertRaises(ToolError): create_project_folder("relative", "safe")
        with self.assertRaises(OSError): create_project_folder(str(self.root / "missing"), "safe")
        self.assertFalse((self.root / "missing").exists())

    async def test_running_task_blocks_creation_before_filesystem_changes(self):
        running = asyncio.create_task(asyncio.Event().wait())
        self.server.active_turns["running"] = running
        try:
            event = await self.create()
            self.assertEqual(event["payload"]["code"],"TURN_RUNNING")
            self.assertFalse((self.root / "新工程").exists())
        finally:
            running.cancel()
            await asyncio.gather(running, return_exceptions=True)
            self.server.active_turns.clear()

    async def test_git_failure_keeps_created_folder_and_reports_warning(self):
        with patch("agent.tools.git._git",new_callable=AsyncMock,side_effect=ToolError("GIT_NOT_FOUND","missing")):
            event = await self.create()
        self.assertEqual(event["type"],"project.opened")
        self.assertIn("GIT_NOT_FOUND",event["payload"]["warning"])
        self.assertTrue((self.root / "新工程").is_dir())

    async def test_rename_inactive_project_does_not_change_active_conversation(self):
        one = self.root / "one"; one.mkdir()
        two = self.root / "two"; two.mkdir()
        project, thread, _ = self.server.projects.open(one, active_model="mock")
        active, active_thread, _ = self.server.projects.open(two, active_model="mock")
        await self.server.handle_message(self.ws,{"type":"thread.rename","thread_id":thread.id,
            "payload":{"project_id":project.id,"title":"Renamed elsewhere"}},set())
        self.assertEqual(self.ws.messages[-1]["type"],"thread.updated")
        self.assertEqual(project.state.get_thread(thread.id).title,"Renamed elsewhere")
        self.assertEqual(self.server.projects.active.id,active.id)
        self.assertEqual(active.active_thread_id,active_thread.id)
