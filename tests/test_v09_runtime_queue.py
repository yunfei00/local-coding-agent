import asyncio
import json
import unittest
from copy import deepcopy
from unittest.mock import AsyncMock
from unittest.mock import patch
from agent.llm.base import ProviderError

import test_unified_runtime as fixture
from test_agent_reliability import BlockingProvider,FakeWebSocket


class RuntimeQueueTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp=fixture.UnifiedLoopTests.asyncSetUp
    asyncTearDown=fixture.UnifiedLoopTests.asyncTearDown

    async def start(self,thread,prompt):
        await self.server.handle_message(self.ws,{'type':'turn.start','thread_id':thread,
            'payload':{'model':'mock','prompt':prompt,'unified':True,'background':True}},set())
        return [e for e in self.ws.messages if e['type']=='turn.started'][-1]['turn_id']

    async def setup_queue(self):
        self.provider=BlockingProvider();self.server.provider=self.provider
        self.server.ensure_model_available=AsyncMock(return_value=True)
        self.server.background.clients.add(self.ws)
        first=await self.start(self.thread.id,'第一项后台任务')
        await asyncio.wait_for(self.provider.started.wait(),5)
        other=self.project.state.create_thread(active_model='mock')
        second=await self.start(other.id,'第二项排队任务')
        return first,second,other

    def run_data(self,ident):
        return json.loads(self.server.store.connection.execute('SELECT data_json FROM agent_execution_runs WHERE id=?',(ident,)).fetchone()[0])

    async def test_queued_cancel_is_persisted_without_model_request(self):
        first,second,other=await self.setup_queue()
        queued=self.run_data(second)
        self.assertEqual(queued['calls'],0);self.assertEqual(queued['unified']['phase'],'queued')
        job=self.server.active_turns[second]
        await self.server.handle_message(self.ws,{'type':'turn.cancel','turn_id':second,'payload':{}},set())
        await asyncio.gather(job,return_exceptions=True)
        self.assertEqual(self.run_data(second)['unified']['phase'],'cancelled')
        self.server.runtime_ledger.recover_executions()
        self.assertEqual(self.run_data(second)['unified']['phase'],'cancelled')
        self.assertEqual(self.server.tasks.runtime.usage()['api_calls'],1)

    async def test_pure_question_does_not_require_unused_workflow_role(self):
        self.server.store.set_setting('workflow.config',json.dumps({'role_models':{'reviewer':'missing-profile'}}))
        self.server.provider=fixture.ScriptedProvider([fixture.final_step('装饰器包装函数以扩展行为。')])
        self.server.ensure_model_available=AsyncMock(return_value=True);self.server.background.clients.add(self.ws)
        ident=await self.start(self.thread.id,'请解释 Python 装饰器')
        await self.server.active_turns[ident]
        self.assertEqual(self.run_data(ident)['unified']['phase'],'completed')
        self.assertEqual(self.server.store.task_plans.list_for_thread(self.thread.id),[])

    async def test_workflow_settings_are_available_without_open_thread(self):
        ws=FakeWebSocket()
        await self.server.tasks.handle(ws,{'type':'task.runtime.workflow.update','thread_id':'','payload':{'config':{'role_models':{},'max_repairs':0}}},set())
        self.assertEqual(ws.messages[-1]['type'],'task.loaded')
        self.assertEqual(ws.messages[-1]['payload']['workflow']['max_repairs'],0)
        await self.server.tasks.handle(ws,{'type':'task.runtime.templates','payload':{}},set())
        self.assertEqual(len(ws.messages[-1]['payload']['templates']),8)

    async def test_live_approval_state_is_persisted_and_cleared_after_decision(self):
        from agent.permissions.approval import ApprovalManager
        self.server.approvals=ApprovalManager()
        provider=fixture.ScriptedProvider([
            fixture.tool_step('git_commit',{'message':'test approval only'}),fixture.final_step('未获授权，不提交')])
        task=asyncio.create_task(self.server.run_tool_turn(self.ws,thread_id=self.thread.id,turn_id='approval-state',prompt='请执行 git commit，提交暂存文件，先等待审批',model='mock',provider=provider,unified=True))
        try:
            for _ in range(300):
                approvals=[e for e in self.ws.messages if e['type']=='approval.requested']
                if approvals:break
                await asyncio.sleep(.01)
            self.assertTrue(approvals)
            run=[e['payload']['runtime'] for e in self.ws.messages if e['type']=='agent.runtime.updated'][-1]
            self.assertEqual(run['workflow_state'],'WAITING_APPROVAL')
            await self.server.handle_message(self.ws,{'type':'approval.respond','payload':{'approval_id':approvals[-1]['payload']['approval_id'],'decision':'deny'}},set())
            await task
            self.assertNotIn('pending_approval',self.run_data(run['id'])['unified'])
        finally:
            if not task.done():task.cancel();await asyncio.gather(task,return_exceptions=True)

    async def test_quota_fallback_stays_on_new_model_across_role_boundaries(self):
        class QuotaAfterWrite(fixture.ScriptedProvider):
            async def stream_chat(self,**kwargs):
                if self.calls>=2:
                    self.calls+=1
                    raise ProviderError('MODEL_QUOTA_EXHAUSTED','isolated quota fault')
                async for chunk in super().stream_chat(**kwargs):yield chunk
        nodes=[{'task_id':'dev','description':'修复','assigned_role':'developer','dependencies':[]},
               {'task_id':'review','description':'独立审查','assigned_role':'reviewer','dependencies':['dev']},
               {'task_id':'test','description':'运行真实测试','assigned_role':'tester','dependencies':['review']}]
        one=QuotaAfterWrite([fixture.tool_step('agent_plan',{'steps':nodes}),fixture.tool_step('write_file',{'path':'calculator.py','content':'def add(a,b): return a+b\n'})])
        two=fixture.ScriptedProvider([fixture.final_step('保留已完成修改'),fixture.tool_step('read_file',{'path':'calculator.py'}),fixture.tool_step('workflow_review',{'decision':'approved','summary':'独立读取后通过'}),fixture.final_step('审查完成'),fixture.tool_step('run_command',{'command':'uv run --no-project python -m unittest discover -s tests -v'}),fixture.final_step('测试通过')])
        clients={'a':one,'b':two}
        for pid,client in clients.items():
            client.max_output_tokens=1024
            client.profile_snapshot={'profile':{'model_profile_id':pid,'model':'model-'+pid,'_connection':{'connection_id':'isolated'}},'capabilities':{'tools':'PASS'},'fingerprint':pid}
        route={'mode':'auto','current':'a','allow_fallback':True,'tried':['a'],'tried_models':[['isolated','model-a']],'switches':[],'reason':['test'],
               'candidates':[{'profile_id':pid,'snapshot':deepcopy(client.profile_snapshot),'reason':['mock capability evidence']} for pid,client in clients.items()]}
        one.route_selection=route;one.profile_snapshot['routing']=route
        def resolve(selection,snapshot=None):
            pid=selection.removeprefix('profile:');return clients[pid],'model-'+pid
        with patch.object(self.server,'chat_provider',side_effect=resolve):
            await self.server.run_tool_turn(self.ws,thread_id=self.thread.id,turn_id='quota-roles',prompt='修复计算器并独立审查测试',model='model-a',provider=one,unified=True)
        run=[e['payload']['runtime'] for e in self.ws.messages if e['type']=='agent.runtime.updated'][-1]
        self.assertEqual(run['outcome'],'completed_verified');self.assertEqual(one.calls,3)
        self.assertEqual([h['model'] for h in run['role_handoffs']],['model-a','model-b','model-b'])
        self.assertEqual(len([e for e in self.ws.messages if e['type']=='tool.completed' and e['payload']['name']=='write_file']),1)

    async def test_planner_refines_pending_steps_through_original_loop(self):
        provider=fixture.ScriptedProvider([
            fixture.tool_step('workflow_template',{'template_id':'bugfix'}),
            fixture.tool_step('read_file',{'path':'calculator.py'}),
            fixture.tool_step('workflow_adjust',{'reason':'已读取源码，根因是错误的减法','changes':[
                {'task_id':'develop','description':'只修复 calculator.py 的 add 运算符'},
                {'task_id':'test','verification':'uv run --no-project python -m unittest discover -s tests -v'}]}),
            fixture.final_step('已细化实际修复与验证要求'),
            fixture.tool_step('write_file',{'path':'calculator.py','content':'def add(a,b): return a+b\n'}),fixture.final_step('修复完成'),
            fixture.tool_step('read_file',{'path':'calculator.py'}),fixture.tool_step('workflow_review',{'decision':'approved','summary':'读取实现确认修复正确'}),fixture.final_step('复核完成'),
            fixture.tool_step('run_command',{'command':'uv run --no-project python -m unittest discover -s tests -v'}),fixture.final_step('测试交付'),
        ])
        await self.server.run_tool_turn(self.ws,thread_id=self.thread.id,turn_id='planner-adjust',prompt='请修复 calculator.py，保留原测试并独立审查和测试',model='mock',provider=provider,unified=True)
        run=[e['payload']['runtime'] for e in self.ws.messages if e['type']=='agent.runtime.updated'][-1]
        self.assertEqual(run['outcome'],'completed_verified')
        self.assertEqual(run['plan']['steps'][1]['description'],'只修复 calculator.py 的 add 运算符')
        self.assertTrue(all(h['output']['evidence_ids'] and h['output']['step_verified'] for h in run['role_handoffs']))

    async def test_preserved_test_write_is_blocked_then_new_test_can_pass(self):
        original=(self.repo/'tests/test_calc.py').read_bytes()
        provider=fixture.ScriptedProvider([
            fixture.tool_step('write_file',{'path':'tests/test_calc.py','content':'# remove original expectations'}),
            fixture.tool_step('write_file',{'path':'calculator.py','content':'def add(a,b): return a+b\n'}),
            fixture.tool_step('write_file',{'path':'tests/test_extra.py','content':'import unittest\nfrom calculator import add\nclass Extra(unittest.TestCase):\n def test_zero(self): self.assertEqual(add(0,0),0)\n'}),
            fixture.final_step('代码和新增测试完成'),
        ])
        await self.server.run_tool_turn(self.ws,thread_id=self.thread.id,turn_id='protected-tests',prompt='修复 calculator.py，保留原测试，新增测试',model='mock',provider=provider,unified=True)
        self.assertEqual((self.repo/'tests/test_calc.py').read_bytes(),original)
        run=[e['payload']['runtime'] for e in self.ws.messages if e['type']=='agent.runtime.updated'][-1]
        self.assertEqual(run['outcome'],'completed_verified')
        self.assertTrue(any(e['type']=='tool.completed' and e['payload']['result'].get('error',{}).get('code')=='ACCEPTANCE_FILE_PROTECTED' for e in self.ws.messages))

    async def test_shell_changed_frozen_contract_cannot_claim_completion(self):
        command="uv run --no-project python -c \"from pathlib import Path; Path('tests/test_calc.py').write_text('# removed')\""
        provider=fixture.ScriptedProvider([fixture.tool_step('run_command',{'command':command}),fixture.final_step('错误地声称完成')])
        await self.server.run_tool_turn(self.ws,thread_id=self.thread.id,turn_id='shell-contract',prompt='修复 calculator.py，保留原测试',model='mock',provider=provider,unified=True)
        run=[e['payload']['runtime'] for e in self.ws.messages if e['type']=='agent.runtime.updated'][-1]
        self.assertEqual(run['error_code'],'ACCEPTANCE_CONTRACT_CHANGED')
        self.assertNotEqual(run['outcome'],'completed_verified')

    async def test_queued_pause_and_resume_preserve_original_settings(self):
        first,second,other=await self.setup_queue()
        original=self.run_data(second)['unified_config']['budget']['api_calls']
        self.assertGreater(original,0)
        await self.server.tasks.handle(self.ws,{'type':'task.runtime.pause','thread_id':other.id,'payload':{'run_id':second}},set())
        self.assertEqual(self.run_data(second)['unified']['phase'],'paused')
        saved=self.server.tasks.settings();saved['budget']['api_calls']=0
        self.server.store.set_setting('orchestration.config',json.dumps(saved))
        first_task=self.server.active_turns[first]
        await self.server.handle_message(self.ws,{'type':'turn.cancel','turn_id':first,'payload':{}},set())
        await asyncio.gather(first_task,return_exceptions=True);await asyncio.sleep(0)
        self.provider.started.clear()
        await self.server.handle_message(self.ws,{'type':'turn.start','thread_id':other.id,'payload':{
            'model':'mock','prompt':'继续原排队任务','unified':True,'background':True,'resume_run_id':second,'confirm_workspace':True}},set())
        await asyncio.wait_for(self.provider.started.wait(),5)
        self.assertEqual(self.run_data(second)['unified_config']['budget']['api_calls'],original)
        self.assertEqual(self.run_data(second)['calls'],1)
        self.assertEqual(self.server.tasks.runtime.usage()['api_calls'],2)

    async def test_queued_restart_retains_goal_zero_usage_and_recovery_entry(self):
        first,second,other=await self.setup_queue()
        queued=self.run_data(second)
        self.server.runtime_ledger.recover_executions()
        restored=self.run_data(second)
        self.assertEqual(restored['unified']['phase'],'paused')
        self.assertEqual(restored['unified_goal'],queued['unified_goal'])
        self.assertEqual(restored['unified_config'],queued['unified_config'])
        self.assertEqual(restored['calls'],0)

    async def test_explicit_confirmed_plan_resume_probes_before_model_and_preserves_steps(self):
        first=fixture.ScriptedProvider([
            fixture.tool_step('agent_plan',{'steps':[
                {'task_id':'dev','description':'修复','assigned_role':'developer','dependencies':[]},
                {'task_id':'review','description':'审查','assigned_role':'reviewer','dependencies':['dev']},
                {'task_id':'test','description':'测试','assigned_role':'tester','dependencies':['review']},
            ]}),
            fixture.tool_step('write_file',{'path':'calculator.py','content':'def add(a,b): return a+b\n'}),fixture.final_step('开发完成'),
            fixture.tool_step('write_file',{'path':'calculator.py','content':'禁止的审查写入'}),
        ])
        await self.server.run_tool_turn(self.ws,thread_id=self.thread.id,turn_id='first',prompt='请修复 calculator.py 并审查测试',model='mock',provider=first,unified=True)
        plan=self.server.store.task_plans.list_for_thread(self.thread.id)[0]
        self.assertEqual(plan['steps'][0]['state'],'completed')
        completed_id=plan['steps'][0]['id']
        self.server.provider=fixture.ScriptedProvider([
            fixture.tool_step('read_file',{'path':'calculator.py'}),fixture.tool_step('workflow_review',{'decision':'approved','summary':'独立读取后通过'}),fixture.final_step('审查完成'),
            fixture.tool_step('run_command',{'command':'uv run --no-project python -m unittest discover -s tests -v'}),fixture.final_step('完成'),
        ])
        self.server.ensure_model_available=AsyncMock(return_value=True)
        self.server.background.clients.add(self.ws)
        await self.server.handle_message(self.ws,{'type':'turn.start','thread_id':self.thread.id,'payload':{
            'model':'mock','prompt':'恢复原任务','unified':True,'background':True,'resume_run_id':plan['id'],'confirm_workspace':True}},set())
        await asyncio.gather(*list(self.server.active_turns.values()))
        data=self.run_data(plan['id']);self.assertEqual(data['unified']['outcome'],'completed_verified')
        restored=self.server.store.task_plans.get(plan['id'])
        self.assertEqual(restored['steps'][0]['id'],completed_id)
        self.assertEqual(restored['steps'][0]['state'],'completed')


if __name__=='__main__':unittest.main()
