"""Only model decisions are scripted; files, commands, journals and approvals are real."""
import asyncio
import json
import os
from pathlib import Path
import shutil
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from agent.core.execution import ExecutionBudget, failure_diagnosis, execution_policy
from agent.llm.base import ProviderChunk
from agent.server.main import AgentServer
from agent.task_plans import mutation_fingerprint
from test_m2_projects import Client, ModelResponses, tool, last_result

ROOT=Path(__file__).resolve().parents[1]


class ExecutionTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='lca-continuation-');self.root=Path(self.temp.name)
        self.env=patch.dict(os.environ,{'LCA_DATA_DIR':str(self.root/'data'),'LCA_OPENAI_API_KEY':''});self.env.start()
        self.repo=self.root/'repo'
        shutil.copytree(ROOT/'manual-fixtures/v04-local-first',self.repo)
        import subprocess
        for args in (['init','-q','-b','main'],['config','user.name','Continuation fixture'],['config','user.email','fixture@example.test'],['add','.'],['commit','-qm','fixture']):
            subprocess.run(['git',*args],cwd=self.repo,check=True,capture_output=True)
        self.server=AgentServer('fixture');self.server.permissions.set_mode('full_access')
        self.project,self.thread,_=self.server.projects.open(self.repo,active_model='single-executor')
        self.client=Client(self.server)

    async def asyncTearDown(self):
        for task in list(self.server.active_turns.values()):task.cancel()
        await asyncio.gather(*list(self.server.active_turns.values()),return_exceptions=True)
        await self.server.close_async();self.server.close();self.env.stop();self.temp.cleanup()

    async def run_model(self,steps,turn='continuation',single=False):
        model=ModelResponses(steps)
        await self.server.run_tool_turn(self.client,thread_id=self.thread.id,turn_id=turn,prompt='Repair calculator and verify actual results',
            model=model.preferred_model,provider=model,single_agent=single)
        return model

    async def test_more_than_16_calls_preserves_patch_results_and_checkpoint(self):
        self.server.max_model_steps=16  # Exercise a short slice independently of defaults.
        steps=[tool('read_file',path='calculator.py'),tool('apply_patch',path='calculator.py',old_text='return a - b',new_text='return a + b'),
               tool('run_command',command='uv run --no-project python -m unittest discover -s tests -v')]
        steps += [tool('file_exists',path=f'probe-{n}.txt') for n in range(14)]
        steps += [tool('git_diff'),ProviderChunk(content='Actual tests and diff passed',done=True)]
        model=await self.run_model(steps)
        self.assertEqual(len(model.seen),19)
        self.assertTrue(any(e['type']=='turn.continuing' for e in self.client.messages))
        self.assertTrue(any(e['type']=='turn.completed' for e in self.client.messages))
        plan=self.server.store.task_plans.list_for_thread(self.thread.id)[0]
        self.assertEqual(plan['execution']['calls'],19)
        self.assertEqual(plan['execution']['continuations'],1)
        calls=self.server.store.task_plans.executions(plan['id'])
        self.assertEqual(sum(c['tool']=='apply_patch' for c in calls),1)
        self.assertIn('return a + b',(self.repo/'calculator.py').read_text())
        checkpoints=self.server.store.connection.execute('select reason from task_checkpoints where plan_id=?',(plan['id'],)).fetchall()
        self.assertIn('model_slice_limit',[r[0] for r in checkpoints])
        self.assertNotIn('return a + b',json.dumps(calls))

    async def test_default_long_task_crosses_old_tool_limit_and_verifies_real_patch(self):
        steps=[tool('file_exists',path=f'probe-{n}') for n in range(45)]
        steps += [tool('read_file',path='calculator.py'),
            tool('apply_patch',path='calculator.py',old_text='return a - b',new_text='return a + b'),
            tool('run_command',command='uv run --no-project python -m unittest discover -s tests -v'),
            tool('git_diff'),ProviderChunk(content='Actual tests and diff passed',done=True)]
        model=await self.run_model(steps)
        self.assertEqual(len(model.seen),50)
        self.assertTrue(any(e['type']=='turn.completed' for e in self.client.messages))
        self.assertIn('return a + b',(self.repo/'calculator.py').read_text())
        self.assertTrue(any(c['tool']=='run_command' and c['status']=='succeeded' and c['exit_code']==0
            for p in self.server.store.task_plans.list_for_thread(self.thread.id)
            for c in self.server.store.task_plans.executions(p['id'])))

    async def test_large_execution_budget_can_be_extended_without_shrinking_or_resetting_usage(self):
        plan_id=self.server.store.task_plans.create(self.thread.id,'Preserve large budget',[{'description':'Inspect'}])
        budget=ExecutionBudget(self.server.store.connection,plan_id,self.thread.id,execution_policy())
        budget.reserve([{'role':'user','content':'Inspect existing workspace'}],[],1024)
        plan=self.server.store.task_plans.get(plan_id)
        before=plan['execution']
        self.assertGreaterEqual(before['limits']['tokens'],10000000)
        await self.server.handle_message(self.client,{'type':'plan.execution.extend','thread_id':self.thread.id,
            'payload':{'plan_id':plan['id']}},set())
        after=self.server.store.task_plans.get(plan['id'])['execution']
        self.assertEqual(after['calls'],before['calls'])
        self.assertEqual(after['reserved_tokens'],before['reserved_tokens'])
        self.assertGreaterEqual(after['limits']['tokens'],before['limits']['tokens'])

    async def test_budget_is_persistent_and_does_not_send_another_request(self):
        self.server.continuation_policy['model_calls']=1
        model=await self.run_model([tool('file_exists',path='calculator.py')])
        self.assertEqual(len(model.seen),1)
        self.assertTrue(any(e['payload'].get('code')=='EXECUTION_BUDGET_EXHAUSTED' for e in self.client.messages))
        plan=self.server.store.task_plans.list_for_thread(self.thread.id)[0]
        model=await self.run_model([ProviderChunk(content='Should never be requested',done=True)],turn='second')
        self.assertEqual(len(model.seen),0)
        self.assertEqual(self.server.store.task_plans.get(plan['id'])['execution']['calls'],1)
        await self.server.handle_message(self.client,{'type':'plan.execution.extend','thread_id':self.thread.id,'payload':{'plan_id':plan['id']}},set())
        updated=self.server.store.task_plans.get(plan['id'])['execution']
        self.assertEqual(updated['calls'],1)
        self.assertEqual(updated['limits']['model_calls'],17)

    async def test_stop_after_continuation_closes_actual_process_tree(self):
        self.server.max_model_steps=2
        command=f'"{os.sys.executable}" -c "import time; print(\'READY\',flush=True); time.sleep(90)"'
        # Call uses the existing real process manager; wait in the model only.
        command=('& ' if os.name=='nt' else '')+command
        model=ModelResponses([tool('start_process',command=command,timeout_seconds=120),tool('file_exists',path='calculator.py'),'block'])
        pending=asyncio.create_task(self.server.run_tool_turn(self.client,thread_id=self.thread.id,turn_id='cancel-slice',prompt='Start and inspect a fixture process',model=model.preferred_model,provider=model))
        await asyncio.wait_for(model.blocked.wait(),15)
        sessions=list(self.project.tools.processes.sessions.values());self.assertTrue(sessions)
        pending.cancel()
        with self.assertRaises(asyncio.CancelledError):await pending
        self.assertTrue(all(s.process.returncode is not None for s in sessions))
        self.assertTrue(any(e['type']=='turn.continuing' for e in self.client.messages))

    async def test_continuation_cap_preserves_progress_and_stops(self):
        self.server.max_model_steps=1
        self.server.continuation_policy['max_continuations']=1
        model=await self.run_model([tool('file_exists',path='calculator.py'),tool('file_exists',path='tests')])
        self.assertEqual(len(model.seen),2)
        plan=self.server.store.task_plans.list_for_thread(self.thread.id)[0]
        self.assertEqual(plan['execution']['continuations'],1)
        self.assertEqual(plan['execution']['status'],'paused')
        self.assertTrue(any(e['payload'].get('code')=='MAX_MODEL_STEPS' for e in self.client.messages))

    async def test_duplicate_start_reuses_actual_owned_process(self):
        command=('& ' if os.name=='nt' else '')+f'"{os.sys.executable}" -c "import time; time.sleep(90)"'
        registry=self.project.tools
        try:
            first=await registry.execute('start_process',{'command':command},owner_id='same-owner')
            second=await registry.execute('start_process',{'command':command},owner_id='same-owner')
            self.assertEqual(first.data['pid'],second.data['pid'])
            self.assertTrue(second.data['already_running'])
            self.assertEqual(len(registry.processes.sessions),1)
        finally:
            await registry.processes.close_owner('same-owner')
        self.assertTrue(all(s.process.returncode is not None for s in registry.processes.sessions.values()))

    async def test_successful_side_effect_shell_is_not_replayed_after_resume(self):
        from agent.task_plans import repeatable_check
        self.server.max_model_steps=1
        self.server.continuation_policy['max_continuations']=0
        command='uv run --no-project python -c "from pathlib import Path; p=Path(\'counter.txt\'); p.write_text(p.read_text()+\'x\' if p.exists() else \'x\')"'
        await self.run_model([tool('run_command',command=command)],turn='first-command')
        self.assertEqual((self.repo/'counter.txt').read_text(),'x')
        await self.run_model([tool('run_command',command=command)],turn='resumed-command')
        self.assertEqual((self.repo/'counter.txt').read_text(),'x')
        result=next(e['payload']['result'] for e in reversed(self.client.messages) if e['type']=='tool.completed')
        self.assertEqual(result['error']['code'],'PLAN_OPERATION_ALREADY_APPLIED')
        self.assertTrue(repeatable_check('run_command',{'command':'uv run --no-project python -m unittest discover -s tests -v'}))
        self.assertFalse(repeatable_check('run_command',{'command':'npm test; echo side-effect'}))

    async def test_token_and_elapsed_budgets_are_enforced_without_model_request(self):
        from agent.llm.base import ProviderError
        db=self.server.store.connection
        policy={'model_calls':10,'max_continuations':1,'tokens':1,'seconds':60}
        tokens=ExecutionBudget(db,'token-unit',self.thread.id,policy)
        with self.assertRaises(ProviderError):tokens.reserve([{'content':'real context'}],[],1)
        self.assertEqual(tokens.data['calls'],0)
        timed=ExecutionBudget(db,'time-unit',self.thread.id,{**policy,'tokens':10000,'seconds':.01})
        await asyncio.sleep(.03)
        with self.assertRaises(ProviderError):timed.reserve([],[],1)
        self.assertEqual(timed.data['calls'],0)

    async def test_guarded_task_rejects_changed_existing_test_expectation(self):
        from agent.llm.router import validate_config
        test=next((self.repo/'tests').glob('test*.py'))
        model=ModelResponses([tool('write_file',path='tests/'+test.name,content='import unittest\nclass Fake(unittest.TestCase):\n def test_fake(self): pass\n'),ProviderChunk(content='All tests pass',done=True)])
        self.server.tasks.provider_factory_override=lambda *_:model
        config=validate_config({'strategy':'single-agent','roles':{'executor':{'model':'single-executor','context_window':262144}},'budget':{'api_calls':30,'api_tokens':2000000,'global_api_calls':100,'global_api_tokens':9000000},'verification_commands':['uv run --no-project python -m unittest discover -s tests -v']})
        await self.server.tasks.handle(self.client,{'type':'task.start','thread_id':self.thread.id,'payload':{'goal':'Repair calculator; preserve original tests','config':config}},set())
        await asyncio.wait_for(asyncio.gather(*list(self.server.active_turns.values())),30)
        task=self.server.store.task_runtime.list(self.thread.id)[0]
        self.assertEqual(task['status'],'paused',task['reason'])
        self.assertEqual(task['verification'][0]['command'],'acceptance contract')
        self.assertFalse(task['verification'][0]['ok'])
        self.assertNotIn('class Fake',test.read_text())

    def test_acceptance_allows_new_tests_and_detects_removed_expectations(self):
        from agent.core.verification import acceptance_snapshot, acceptance_changes
        baseline=acceptance_snapshot(self.repo)
        extra=self.repo/'tests/test_extra.py';extra.write_text('new test')
        self.assertEqual(acceptance_changes(self.repo,baseline),[])
        existing=next(p for p in (self.repo/'tests').glob('test*.py') if p!=extra)
        existing.write_text('changed expectations')
        self.assertIn(str(existing.relative_to(self.repo)),acceptance_changes(self.repo,baseline))

    async def test_blocked_recovery_probes_real_workspace_without_replaying_writes(self):
        plans=self.server.store.task_plans
        pid=plans.create(self.thread.id,'Recover existing work',[{'description':'Already written'},{'description':'Check environment'}])
        first,second=plans.get(pid)['steps']
        plans.record_execution(pid,first['id'],'write','past','write_file',{'ok':True},mutation_fingerprint('write_file',{'path':'kept.txt','content':'kept'}))
        plans.update_step(pid,first['id'],'completed',[{'ok':True,'tool_call_id':'write'}])
        (self.repo/'kept.txt').write_text('kept')
        plans.update_step(pid,second['id'],'blocked')
        plans.set_recovery(pid,second['id'],'read_process','PROCESS_EXITED')
        plans.checkpoint(pid,'failed_window')
        await self.server.handle_message(self.client,{'type':'plan.recover','thread_id':self.thread.id,'payload':{'plan_id':pid}},set())
        restored=plans.get(pid)
        self.assertEqual([s['state'] for s in restored['steps']],['completed','in_progress'])
        self.assertEqual((self.repo/'kept.txt').read_text(),'kept')
        self.assertEqual(plans.latest_checkpoint(pid)['reason'],'recovery_verified_workspace')
        self.assertEqual(sum(c['tool']=='write_file' for c in plans.executions(pid)),1)

    async def test_failure_limit_exposes_safe_last_tool_diagnosis(self):
        await self.run_model([tool('read_file',path=f'missing-{n}') for n in range(4)])
        failed=next(e for e in self.client.messages if e['payload'].get('code')=='TOOL_FAILURE_LIMIT')
        self.assertEqual(failed['payload']['last_tool'],'read_file')
        self.assertEqual(failed['payload']['last_failure_code'],'FILE_NOT_FOUND')
        self.assertEqual(failed['payload']['diagnosis']['category'],'environment')
        self.assertIn('action',failed['payload']['diagnosis'])
        plan=self.server.store.task_plans.list_for_thread(self.thread.id)[0]
        calls=self.server.store.task_plans.executions(plan['id'])
        self.assertTrue(all('duration_ms' in c['metadata'] for c in calls))
        self.assertNotIn('missing-0',json.dumps(calls))

    async def test_missing_workspace_cannot_clear_blocked(self):
        plans=self.server.store.task_plans
        pid=plans.create(self.thread.id,'Recover missing environment',[{'description':'Inspect workspace'}])
        step=plans.active_step(pid)
        plans.update_step(pid,step['id'],'blocked')
        moved=self.repo.with_name('temporarily-moved')
        self.repo.rename(moved)
        try:
            with self.assertRaises(ValueError):
                await self.server.recover_plan(self.client,self.project,pid,self.thread.id)
            self.assertEqual(plans.active_step(pid)['state'],'blocked')
            self.assertEqual(plans.latest_checkpoint(pid)['reason'],'recovery_probe_failed')
        finally:
            moved.rename(self.repo)

    async def test_failed_test_cannot_be_hidden_by_unrelated_success(self):
        await self.run_model([tool('run_command',command='uv run --no-project python -m unittest discover -s tests -v'),
            tool('file_exists',path='calculator.py'),ProviderChunk(content='All tests passed',done=True)])
        self.assertFalse(any(e['type']=='turn.completed' for e in self.client.messages))
        self.assertTrue(any(e['payload'].get('code')=='PLAN_TOOLS_UNRESOLVED' for e in self.client.messages))
        plan=self.server.store.task_plans.list_for_thread(self.thread.id)[0]
        self.assertEqual(plan['steps'][0]['state'],'blocked')

    async def test_restart_uncertain_mutation_requires_new_approval(self):
        pid=self.server.store.task_plans.create(self.thread.id,'Uncertain operation',[{'description':'Verify uncertain write'}])
        step=self.server.store.task_plans.active_step(pid)
        args={'path':'uncertain.txt','content':'ordinary-fixture-content'}
        self.server.store.task_plans.record_execution(pid,step['id'],'crash','past','write_file',fingerprint=mutation_fingerprint('write_file',args))
        await self.server.close_async();self.server.close()
        self.server=AgentServer('fixture');self.server.permissions.set_mode('full_access')
        self.project,_,_=self.server.projects.open(self.repo,active_model='single-executor')
        class Deny(Client):
            async def send_json(inner,event):
                inner.messages.append(event)
                if event['type']=='approval.requested':inner.server.approvals.respond(event['payload']['approval_id'],'deny')
        self.client=Deny(self.server)
        await self.run_model([tool('write_file',**args),ProviderChunk(content='Denied',done=True)],single=True)
        self.assertFalse((self.repo/'uncertain.txt').exists())
        self.assertTrue(any(e['type']=='approval.requested' and e['payload']['risk']=='uncertain_operation' for e in self.client.messages))

    def test_static_failure_classification_never_persists_body(self):
        for tool_name,code,category in [('desktop_inspect','DESKTOP_WINDOW_STALE','environment'),('write_file','APPROVAL_DENIED','permission'),('read_file','REPEATED_TOOL_CALL','repetition'),('run_command','TOOL_FAILED','test'),('desktop_type_text','DESKTOP_EDIT_REQUIRED','compatibility')]:
            self.assertEqual(failure_diagnosis(tool_name,code)['category'],category)
        self.assertEqual(failure_diagnosis('x','password=must-not-log')['error_code'],'TOOL_FAILED')
