import asyncio
import json
import unittest
from unittest.mock import AsyncMock,patch
import test_unified_runtime as fixture
from test_agent_reliability import BlockingProvider
from agent.persistence.backup import inspect_backup


class MaintenanceTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp=fixture.UnifiedLoopTests.asyncSetUp
    asyncTearDown=fixture.UnifiedLoopTests.asyncTearDown

    async def request(self,kind,payload=None):
        await self.server.handle_message(self.ws,{'type':kind,'payload':payload or {}},set())
        return self.ws.messages[-1]

    async def test_optional_missing_tools_do_not_block_first_run_or_contact_models(self):
        with patch('shutil.which',return_value=None),patch.object(self.server.provider,'get_status',AsyncMock(side_effect=AssertionError('unexpected provider request'))):
            event=await self.request('maintenance.environment')
        self.assertEqual(event['type'],'maintenance.loaded')
        self.assertTrue(event['payload']['backend_ready']);self.assertFalse(event['payload']['nonessential_dependencies_blocking'])
        self.assertTrue(all(not available for available in event['payload']['tools'].values()))

    async def test_no_git_can_create_project_and_keep_real_folder(self):
        with patch('shutil.which',return_value=None):
            event=await self.request('project.create',{'parent_path':str(self.root),'name':'无 Git 工程','initialize_git':True})
        self.assertNotEqual(event['type'],'error',event)
        self.assertTrue((self.root/'无 Git 工程').is_dir())
        self.assertIn('Git',json.dumps(event))
        self.assertTrue(self.server.projects.active.workspace.root.samefile(self.root/'无 Git 工程'))

    async def test_update_pauses_running_and_queued_tasks_preserving_budget_and_backup(self):
        provider=BlockingProvider();self.server.provider=provider;self.server.ensure_model_available=AsyncMock(return_value=True)
        self.server.background.clients.add(self.ws)
        async def start(thread):
            await self.server.handle_message(self.ws,{'type':'turn.start','thread_id':thread,'payload':{
                'model':'mock','prompt':'请解释装饰器','unified':True,'background':True}},set())
            return [e['turn_id'] for e in self.ws.messages if e['type']=='turn.started'][-1]
        first=await start(self.thread.id);await asyncio.wait_for(provider.started.wait(),5)
        other=self.project.state.create_thread(active_model='mock');second=await start(other.id)
        event=await self.request('maintenance.prepare_update')
        self.assertEqual(event['type'],'maintenance.loaded',event)
        self.assertTrue(event['payload']['tasks_paused']);inspect_backup(event['payload']['path'])
        for ident,calls in [(first,1),(second,0)]:
            row=self.server.store.connection.execute('SELECT data_json FROM agent_execution_runs WHERE id=?',(ident,)).fetchone()
            data=json.loads(row[0]);self.assertEqual(data['unified']['phase'],'paused');self.assertEqual(data['calls'],calls)
        self.assertFalse(any(not task.done() for task in self.server.active_turns.values()))
        await self.server.handle_message(self.ws,{'type':'turn.start','thread_id':self.thread.id,'payload':{'model':'mock','prompt':'新任务','unified':True,'background':True}},set())
        self.assertEqual(self.ws.messages[-1]['payload']['code'],'UPDATE_PENDING')
        await self.request('maintenance.cancel_update');self.assertFalse(self.server.update_preparing)


if __name__=='__main__':unittest.main()
