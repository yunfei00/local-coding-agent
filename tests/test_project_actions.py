"""Non-destructive project removal through the actual registry/protocol/store."""
import asyncio
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from agent.server.main import AgentServer
from agent.server.projects import ProjectRegistry
from test_agent_reliability import FakeWebSocket


class ProjectActionTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.env = patch.dict(os.environ, {"LCA_DATA_DIR":str(self.root / "data")})
        self.env.start()
        self.server = AgentServer("test")
        self.ws = FakeWebSocket()

    async def asyncTearDown(self):
        running = list(self.server.active_turns.values())
        for task in running: task.cancel()
        await asyncio.gather(*running, return_exceptions=True)
        self.server.active_turns.clear()
        await self.server.close_async()
        self.server.close()
        self.env.stop()
        self.temp.cleanup()

    async def request(self, kind, payload=None):
        await self.server.handle_message(self.ws, {"type":kind, "payload":payload or {}}, set())
        return self.ws.messages[-1]

    async def open(self, name, with_thread=True):
        path = self.root / name
        path.mkdir(exist_ok=True)
        (path / "keep.txt").write_text("keep user code", encoding="utf-8")
        await self.request("project.open", {"path":str(path), "defer_thread":True})
        project = self.server.projects.active
        if with_thread:
            await self.request("thread.create", {"initial_prompt":"Project " + name})
        return project

    async def test_targeted_information_does_not_switch_project(self):
        first = await self.open("first")
        second = await self.open("second")
        result = await self.request("project.get", {"project_id":first.id})
        self.assertEqual(result["payload"]["project"]["id"], first.id)
        self.assertEqual(self.server.projects.active.id, second.id)
        for bad in ("missing", "", None):
            result = await self.request("project.get", {"project_id":bad})
            self.assertEqual(result["payload"]["code"], "PROJECT_NOT_FOUND")

    async def test_inactive_remove_keeps_messages_checkpoint_budget_and_files(self):
        first = await self.open("first")
        thread = first.active_thread()
        first.state.append_exchange(thread.id, user="saved user message", assistant="saved answer")
        runtime = self.server.store.task_runtime
        task = runtime.create(thread.id, "Paused task", {}, first.path)
        task["status"] = "paused"; runtime.save(task)
        runtime.plans.checkpoint(task["id"], "before hiding project")
        with runtime.db:
            runtime.db.execute("INSERT INTO model_requests VALUES(?,?,?,?,?,?,?,?,?,?)", (
                "retained", task["id"], "api", "executor", "configured-model", 321, 0.0, "interrupted", "{}", 1.0))
        usage, global_usage = runtime.usage(task["id"]), runtime.usage()
        checkpoint = runtime.plans.latest_checkpoint(task["id"])
        second = await self.open("second")
        result = await self.request("project.remove", {"project_id":first.id})
        self.assertEqual(result["type"], "project.removed")
        self.assertFalse(result["payload"]["active_changed"])
        self.assertEqual(self.server.projects.active.id, second.id)
        self.assertEqual(len(self.server.store.list_projects()), 2)
        self.assertEqual(runtime.get(task["id"])["status"], "paused")
        self.assertEqual(runtime.usage(task["id"]), usage)
        self.assertEqual(runtime.usage(), global_usage)
        self.assertEqual(runtime.plans.latest_checkpoint(task["id"]), checkpoint)
        self.assertEqual((self.root / "first/keep.txt").read_text(), "keep user code")
        restored = ProjectRegistry(self.server.store)
        self.assertIsNone(restored.get(first.id))
        reopened, same_thread, created = restored.open(first.path, active_model=None, defer_thread=True)
        self.assertFalse(created)
        self.assertEqual(reopened.id, first.id)
        self.assertEqual(same_thread.id, thread.id)
        self.assertEqual(reopened.state.get_messages(thread.id)[0]["content"], "saved user message")
        self.assertEqual(runtime.usage(task["id"]), usage)

    async def test_active_remove_falls_back_without_creating_placeholder(self):
        other = await self.open("other", with_thread=False)
        active = await self.open("active")
        result = await self.request("project.remove", {"project_id":active.id})
        self.assertEqual(result["payload"]["project"]["id"], other.id)
        self.assertTrue(result["payload"]["active_changed"])
        self.assertIsNone(result["payload"]["active_thread"])
        self.assertEqual(self.server.store.list_threads(other.id), [])

    async def test_last_remove_and_retry_stay_empty_after_restart(self):
        project = await self.open("only")
        for _ in range(2):
            result = await self.request("project.remove", {"project_id":project.id})
            self.assertEqual(result["type"], "project.removed")
            self.assertIsNone(result["payload"]["project"])
            self.assertEqual(result["payload"]["projects"], [])
        restored = ProjectRegistry(self.server.store)
        self.assertEqual(restored.list_projects(), [])
        self.assertIsNone(restored.active)
        result = await self.request("project.select", {"project_id":project.id})
        self.assertEqual(result["payload"]["code"], "PROJECT_NOT_FOUND")
        self.assertEqual(len(self.server.store.list_projects()), 1)

    async def test_running_project_is_blocked_but_other_project_can_be_removed(self):
        inactive = await self.open("inactive")
        active = await self.open("active")
        running = asyncio.create_task(asyncio.Event().wait())
        self.server.active_turns["owned"] = running
        self.server.active_turn_threads["owned"] = active.active_thread_id
        result = await self.request("project.remove", {"project_id":active.id})
        self.assertEqual(result["payload"]["code"], "PROJECT_BUSY")
        result = await self.request("project.remove", {"project_id":inactive.id})
        self.assertEqual(result["type"], "project.removed")
        self.assertFalse(running.done())
        self.assertEqual(self.server.projects.active.id, active.id)

    async def test_persisted_running_or_uncertain_cleanup_blocks_removal(self):
        project = await self.open("active")
        runtime = self.server.store.task_runtime
        task = runtime.create(project.active_thread_id, "Orphan running task", {}, project.path)
        task["status"] = "executing"; runtime.save(task)
        result = await self.request("project.remove", {"project_id":project.id})
        self.assertEqual(result["payload"]["code"], "PROJECT_BUSY")
        task.update(status="paused", cleanup_error={"code":"PROCESS_CLEANUP_FAILED"}); runtime.save(task)
        result = await self.request("project.remove", {"project_id":project.id})
        self.assertEqual(result["payload"]["code"], "PROJECT_STOP_INCOMPLETE")
        self.assertIsNotNone(self.server.projects.get(project.id))

    async def test_storage_failure_does_not_hide_project_or_change_active(self):
        project = await self.open("active")
        self.server.store.connection.execute("PRAGMA query_only=ON")
        try:
            result = await self.request("project.remove", {"project_id":project.id})
            self.assertEqual(result["payload"]["code"], "PROJECT_REMOVE_FAILED")
            self.assertEqual(self.server.projects.active.id, project.id)
            self.assertIsNone(self.server.store.get_setting("project.hidden:" + project.id))
        finally:
            self.server.store.connection.execute("PRAGMA query_only=OFF")

    async def test_invalid_id_and_unscoped_execution_do_not_hide_anything(self):
        project = await self.open("active")
        result = await self.request("project.remove", {"project_id":"unknown"})
        self.assertEqual(result["payload"]["code"], "PROJECT_NOT_FOUND")
        self.server.active_turns["unscoped"] = asyncio.create_task(asyncio.Event().wait())
        result = await self.request("project.remove", {"project_id":project.id})
        self.assertEqual(result["payload"]["code"], "PROJECT_BUSY")
        self.assertEqual(len(self.server.projects.list_projects()), 1)

    async def test_temporarily_unavailable_path_reopens_original_registration(self):
        project = await self.open("company-drive")
        thread_id = project.active_thread_id
        await self.request("project.remove", {"project_id":project.id})
        with patch("agent.server.projects.Workspace", side_effect=OSError("Temporarily offline")):
            restored = ProjectRegistry(self.server.store)
        self.assertEqual(restored.list_projects(), [])
        reopened, thread, created = restored.open(project.path, active_model=None, defer_thread=True)
        self.assertFalse(created)
        self.assertEqual(reopened.id, project.id)
        self.assertEqual(thread.id, thread_id)
        self.assertEqual(len(self.server.store.list_projects()), 1)
