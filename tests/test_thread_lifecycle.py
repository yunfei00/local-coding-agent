"""Draft navigation, scoped deletion and durable task audit protection."""
import asyncio
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from agent.persistence.store import SQLiteStore
from agent.server.main import AgentServer
from agent.server.projects import ProjectRegistry
from test_agent_reliability import FakeWebSocket


class ThreadLifecycleTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.project_path = self.root / "project"
        self.project_path.mkdir()
        (self.project_path / "keep.txt").write_text("user content", encoding="utf-8")
        self.env = patch.dict(os.environ, {"LCA_DATA_DIR":str(self.root / "data")})
        self.env.start()
        self.server = AgentServer("test")
        self.ws = FakeWebSocket()

    async def asyncTearDown(self):
        await self.server.close_async()
        self.server.close()
        self.env.stop()
        self.temp.cleanup()

    async def request(self, operation, payload=None, thread_id=None):
        await self.server.handle_message(self.ws, {"type":operation, "payload":payload or {}, "thread_id":thread_id}, set())
        return self.ws.messages[-1]

    async def open(self):
        return await self.request("project.open", {"path":str(self.project_path), "defer_thread":True})

    async def create(self, prompt="Fix a real project"):
        result = await self.request("thread.create", {"initial_prompt":prompt})
        return result["payload"]["thread"]["id"]

    async def test_open_and_select_empty_project_never_persist_a_placeholder(self):
        event = await self.open()
        self.assertIsNone(event["payload"]["active_thread"])
        project = self.server.projects.active
        for _ in range(4):
            event = await self.request("project.select", {"project_id":project.id, "defer_thread":True})
            self.assertEqual(event["payload"]["threads"], [])
        self.assertEqual(self.server.store.list_threads(project.id), [])

    async def test_first_content_names_one_thread_and_empty_content_is_rejected(self):
        await self.open()
        bad = await self.request("thread.create", {"initial_prompt":"  "})
        self.assertEqual(bad["payload"]["code"], "INVALID_PROMPT")
        self.assertEqual(self.server.projects.active.state.list_threads(), [])
        thread_id = await self.create("  Build reports\nwith tests  ")
        self.assertEqual(self.server.projects.active.state.get_thread(thread_id).title, "Build reports with tests")
        self.assertEqual(len(self.server.store.list_threads(self.server.projects.active.id)), 1)

    async def test_delete_last_thread_keeps_files_and_stays_empty_after_restart(self):
        await self.open()
        thread_id = await self.create()
        project = self.server.projects.active
        project.state.append_exchange(thread_id, user="secret body", assistant="result")
        result = await self.request("thread.delete", {"project_id":project.id}, thread_id)
        self.assertEqual(result["type"], "thread.deleted")
        self.assertIsNone(result["payload"]["active_thread"])
        self.assertEqual((self.project_path / "keep.txt").read_text(), "user content")
        restored = ProjectRegistry(self.server.store).get(project.id)
        self.assertEqual(restored.state.list_threads(), [])
        self.assertIsNone(restored.active_thread_id)
        self.assertEqual(self.server.store.list_messages(thread_id)[0]["content"], "secret body")

    async def test_delete_is_project_scoped_and_does_not_switch_active_project(self):
        await self.open()
        first = self.server.projects.active
        thread_id = await self.create()
        other_path = self.root / "other"
        other_path.mkdir()
        other = await self.request("project.open", {"path":str(other_path), "defer_thread":True})
        other_id = other["payload"]["project"]["id"]
        wrong = await self.request("thread.delete", {"project_id":other_id}, thread_id)
        self.assertEqual(wrong["payload"]["code"], "THREAD_NOT_FOUND")
        self.assertIsNotNone(first.state.get_thread(thread_id))
        deleted = await self.request("thread.delete", {"project_id":first.id}, thread_id)
        self.assertEqual(deleted["type"], "thread.deleted")
        self.assertEqual(self.server.projects.active.id, other_id)

    async def test_delete_repairs_active_pointer_without_creating_a_new_thread(self):
        await self.open()
        older = await self.create("First")
        newer = await self.create("Second")
        result = await self.request("thread.delete", {}, newer)
        self.assertEqual(result["payload"]["active_thread"]["id"], older)
        self.assertEqual(len(result["payload"]["threads"]), 1)

    async def test_rename_title_and_activity_survive_reopening(self):
        await self.open()
        thread_id = await self.create()
        project = self.server.projects.active
        before = project.state.get_thread(thread_id).updated_at
        with patch("agent.server.state.now_iso", return_value="2099-01-01T00:00:00+00:00"):
            result = await self.request("thread.rename", {"title":"Updated title"}, thread_id)
        self.assertEqual(result["type"], "thread.updated")
        restored = ProjectRegistry(self.server.store).get(project.id).state.get_thread(thread_id)
        self.assertEqual(restored.title, "Updated title")
        self.assertGreater(restored.updated_at, before)

    async def test_unfinished_tasks_block_delete_and_cancelled_audit_survives(self):
        await self.open()
        thread_id = await self.create()
        runtime = self.server.store.task_runtime
        task = runtime.create(thread_id, "Goal", {"budget":{"api_calls":3}}, str(self.project_path))
        for status in ("pending", "paused", "awaiting_approval"):
            task["status"] = status
            runtime.save(task)
            result = await self.request("thread.delete", {}, thread_id)
            self.assertEqual(result["payload"]["code"], "THREAD_BUSY")
        task["status"] = "cancelled"
        runtime.save(task)
        with runtime.db:
            runtime.db.execute("INSERT INTO model_requests VALUES(?,?,?,?,?,?,?,?,?,?)", (
                "retained-call", task["id"], "api", "executor", "test-model", 123, 0.0, "interrupted", "{}", 1.0))
        before = runtime.get(task["id"])
        before_usage = runtime.usage(task["id"])
        result = await self.request("thread.delete", {}, thread_id)
        self.assertEqual(result["type"], "thread.deleted")
        self.assertEqual(runtime.get(task["id"]), before)
        self.assertEqual(runtime.usage(task["id"]), before_usage)
        self.assertEqual(before_usage["reserved_tokens"], 123)

    async def test_running_turn_blocks_deletion(self):
        await self.open()
        thread_id = await self.create()
        running = asyncio.create_task(asyncio.Event().wait())
        self.server.active_turns["controlled"] = running
        try:
            result = await self.request("thread.delete", {}, thread_id)
            self.assertEqual(result["payload"]["code"], "THREAD_BUSY")
        finally:
            running.cancel()
            await asyncio.gather(running, return_exceptions=True)
            self.server.active_turns.clear()

    async def test_confirmed_delete_cancels_paused_tasks_without_losing_budget(self):
        await self.open()
        thread_id = await self.create()
        runtime = self.server.store.task_runtime
        task = runtime.create(thread_id, "Old paused task", {}, str(self.project_path))
        task["status"] = "paused"
        runtime.save(task)
        with runtime.db:
            runtime.db.execute("INSERT INTO model_requests VALUES(?,?,?,?,?,?,?,?,?,?)", (
                "delete-retained", task["id"], "api", "executor", "model", 321, 0.0, "interrupted", "{}", 1.0))
        before = runtime.usage(task["id"])
        result = await self.request("thread.delete", {"cancel_tasks":True}, thread_id)
        self.assertEqual(result["type"], "thread.deleted")
        self.assertEqual(runtime.get(task["id"])["status"], "cancelled")
        self.assertEqual(runtime.usage(task["id"]), before)
        self.assertEqual((self.project_path / "keep.txt").read_text(), "user content")

    async def test_confirmed_delete_stops_only_target_conversation(self):
        await self.open()
        target = await self.create("Delete this")
        other = await self.create("Keep this")
        stopped = asyncio.Event()
        async def controlled():
            try:
                await asyncio.Event().wait()
            finally:
                stopped.set()
        own = asyncio.create_task(controlled())
        unrelated = asyncio.create_task(asyncio.Event().wait())
        self.server.active_turns.update(target_turn=own, other_turn=unrelated)
        self.server.active_turn_threads.update(target_turn=target, other_turn=other)
        await asyncio.sleep(0)
        try:
            result = await self.request("thread.delete", {"cancel_tasks":True}, target)
            self.assertEqual(result["type"], "thread.deleted")
            self.assertTrue(stopped.is_set())
            self.assertFalse(unrelated.done())
            self.assertIsNotNone(self.server.projects.active.state.get_thread(other))
        finally:
            unrelated.cancel()
            await asyncio.gather(own, unrelated, return_exceptions=True)
            self.server.active_turns.clear()
            self.server.active_turn_threads.clear()

    async def test_delete_retry_is_idempotent(self):
        await self.open()
        thread_id = await self.create()
        for _ in range(2):
            result = await self.request("thread.delete", {"cancel_tasks":True}, thread_id)
            self.assertEqual(result["type"], "thread.deleted")
            self.assertEqual(result["payload"]["threads"], [])

    async def test_running_task_without_local_owner_retains_conversation(self):
        await self.open()
        thread_id = await self.create()
        runtime = self.server.store.task_runtime
        task = runtime.create(thread_id, "Owned by another process", {}, str(self.project_path))
        task["status"] = "executing"
        runtime.save(task)
        result = await self.request("thread.delete", {"cancel_tasks":True}, thread_id)
        self.assertEqual(result["payload"]["code"], "THREAD_STOP_INCOMPLETE")
        self.assertIn("original instance", result["payload"]["message"])
        self.assertEqual(runtime.get(task["id"])["status"], "executing")
        self.assertIsNotNone(self.server.projects.active.state.get_thread(thread_id))

    async def test_new_turn_started_during_shutdown_prevents_deletion(self):
        await self.open()
        thread_id = await self.create()
        async def restart_during_cleanup():
            try:
                await asyncio.Event().wait()
            finally:
                self.server.active_turns["new"] = asyncio.create_task(asyncio.Event().wait())
                self.server.active_turn_threads["new"] = thread_id
        original = asyncio.create_task(restart_during_cleanup())
        self.server.active_turns["old"] = original
        self.server.active_turn_threads["old"] = thread_id
        await asyncio.sleep(0)
        try:
            result = await self.request("thread.delete", {"cancel_tasks":True}, thread_id)
            self.assertEqual(result["payload"]["code"], "THREAD_STOP_INCOMPLETE")
            self.assertIsNotNone(self.server.projects.active.state.get_thread(thread_id))
            self.assertFalse(self.server.active_turns["new"].done())
        finally:
            for running in self.server.active_turns.values():
                running.cancel()
            await asyncio.gather(*self.server.active_turns.values(), return_exceptions=True)
            self.server.active_turns.clear()
            self.server.active_turn_threads.clear()
