"""生产 Agent 入口的追加消息与取消回归，不代替被测 Agent 实现代码。"""
import asyncio
import json
import os
import subprocess
import sys
import unittest
from unittest.mock import AsyncMock

import test_unified_runtime as fixtures
from test_agent_reliability import FakeWebSocket, ScriptedProvider, final_step, tool_step
from agent.llm.base import ProviderError
from agent.server.main import AgentServer
from agent.task_plans import mutation_fingerprint
from agent.core.unified_runtime import requested_intent,workspace_snapshot


class RuntimeIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.fixture=fixtures.UnifiedLoopTests('runTest')
        await self.fixture.asyncSetUp()
        self.server=self.fixture.server
        self.thread=self.fixture.thread
        self.repo=self.fixture.repo

    async def asyncTearDown(self):
        await self.fixture.asyncTearDown()

    def test_explicit_gui_actions_are_not_misread_as_analysis_by_inspect_word(self):
        value=requested_intent('在桌面窗口输入显示名并点击保存，用 desktop_inspect 读取结果')
        self.assertEqual(value['kind'],'interaction');self.assertFalse(value['read_only'])
        self.assertTrue(requested_intent('只分析窗口，不点击任何按钮')['read_only'])
        self.assertTrue(requested_intent('请解释如何在窗口点击保存')['pure_question'])
        self.assertEqual(requested_intent('在桌面 Settings 窗口将显示名称修改为中文，然后点击保存')['kind'],'interaction')
        self.assertEqual(requested_intent('修复 src/App.tsx 界面，让用户点击保存时显示正确状态')['kind'],'change')

    def test_application_runtime_profile_is_not_a_source_code_change(self):
        before=workspace_snapshot(self.repo)
        runtime=self.repo/'.runtime';runtime.mkdir();(runtime/'saved.json').write_text('{"value":"synthetic"}')
        self.assertEqual(workspace_snapshot(self.repo),before)

    async def test_gui_prose_without_actual_action_cannot_complete(self):
        ws=FakeWebSocket()
        await self.server.run_tool_turn(ws,thread_id=self.thread.id,turn_id='gui-prose',prompt='在桌面窗口输入姓名并点击保存',model='mock',provider=ScriptedProvider([final_step('已点击保存')]),unified=True)
        self.assertTrue(any(e['payload'].get('code')=='AGENT_NO_INTERACTION_EVIDENCE' for e in ws.messages))

    async def test_gui_tool_success_does_not_claim_independent_validation(self):
        self.server._authorize_tool=AsyncMock(return_value={'ok':True,'changed_paths':[],'summary':'unit action success','data':{}})
        ws=FakeWebSocket()
        await self.server.run_tool_turn(ws,thread_id=self.thread.id,turn_id='gui-evidence',prompt='在桌面窗口点击 Settings',model='mock',provider=ScriptedProvider([tool_step('desktop_click',{'window_id':'unit-window','selector':{'name':'Settings'}}),final_step('已操作，尚无独立验收合约')]),unified=True)
        runtime=[e['payload']['runtime'] for e in ws.messages if e['type']=='agent.runtime.updated'][-1]
        self.assertEqual(runtime['phase'],'completed');self.assertEqual(runtime['outcome'],'completed_unverified')
        self.assertEqual(runtime['level'],'manual')

    async def test_interrupted_review_requires_approval_and_is_not_success_evidence(self):
        plans=self.server.store.task_plans
        plan_id=plans.create(self.thread.id,'核对中断',[{'description':'验证'}]);step=plans.active_step(plan_id)
        fingerprint=mutation_fingerprint('write_file',{'path':'uncertain.txt','content':'unknown'})
        plans.record_execution(plan_id,step['id'],'unknown-call','past','write_file',fingerprint=fingerprint)
        await self.server.close_async();self.server.close()
        self.server=AgentServer('test');self.fixture.server=self.server
        requested=[]
        async def deny(*args,**kwargs):requested.append(kwargs);return 'deny'
        self.server.approvals.request=deny
        request={'type':'plan.operation.review','thread_id':self.thread.id,'payload':{'plan_id':plan_id,'call_id':'unknown-call','confirm_workspace':True}}
        ws=FakeWebSocket();await self.server.handle_message(ws,request,set())
        plans=self.server.store.task_plans
        self.assertTrue(plans.uncertain_operation(plan_id,'check'))
        self.assertEqual(requested[-1]['risk'],'uncertain_operation_review')
        async def approve(*args,**kwargs):return 'allow_once'
        self.server.approvals.request=approve
        await self.server.handle_message(ws,request,set())
        self.assertFalse(plans.uncertain_operation(plan_id,'check'))
        self.assertTrue(plans.uncertain_operation(plan_id,fingerprint))
        self.assertEqual(plans.active_step(plan_id)['state'],'pending')
        with self.assertRaises(ValueError):plans.execution_evidence(plan_id,step['id'],['unknown-call'])
        self.assertFalse((self.repo/'uncertain.txt').exists())

    async def test_review_approval_can_return_over_the_same_websocket(self):
        from aiohttp import web
        from aiohttp.test_utils import TestClient,TestServer
        plans=self.server.store.task_plans
        plan_id=plans.create(self.thread.id,'核对中断',[{'description':'验证'}]);step=plans.active_step(plan_id)
        plans.record_execution(plan_id,step['id'],'review-ws-call','past','run_command',fingerprint='unknown-effect')
        await self.server.close_async();self.server.close()
        self.server=AgentServer('test');self.fixture.server=self.server
        app=web.Application();app.router.add_get('/ws',self.server.websocket)
        async with TestClient(TestServer(app)) as client:
            ws=await client.ws_connect('/ws',headers={'Authorization':'Bearer test'});await ws.receive_json()
            await ws.send_json({'type':'plan.operation.review','request_id':'review-request','thread_id':self.thread.id,'payload':{'plan_id':plan_id,'call_id':'review-ws-call','confirm_workspace':True}})
            approval=await asyncio.wait_for(ws.receive_json(),3)
            self.assertEqual(approval['type'],'approval.requested')
            await ws.send_json({'type':'approval.respond','request_id':'review-response','payload':{'approval_id':approval['payload']['approval_id'],'decision':'allow_once'}})
            events=[await asyncio.wait_for(ws.receive_json(),3) for _ in range(2)]
            self.assertEqual({e['type'] for e in events},{'approval.resolved','plan.loaded'})
            self.assertFalse(self.server.store.task_plans.uncertain_operation(plan_id,'check'))
            self.assertEqual(self.server.store.task_plans.active_step(plan_id)['state'],'pending')
            await ws.close()

    async def test_completed_plan_with_reviewed_interruption_resumes_same_owner(self):
        plans=self.server.store.task_plans
        plan_id=plans.create(self.thread.id,'修复加法',[{'description':'修复并验证'}]);step=plans.active_step(plan_id)
        plans.record_execution(plan_id,step['id'],'unconfirmed-call','past','run_command',fingerprint='unknown-effect')
        await self.server.close_async();self.server.close()
        self.server=AgentServer('test');self.fixture.server=self.server
        async def approve(*args,**kwargs):return 'allow_once'
        self.server.approvals.request=approve
        provider=ScriptedProvider([tool_step('write_file',{'path':'calculator.py','content':'def add(a,b): return a+b\n'}),final_step('真实修改与测试完成')])
        ws=FakeWebSocket()
        await self.server.run_tool_turn(ws,thread_id=self.thread.id,turn_id='first-attempt',prompt='请修复 calculator.py 加法',model='mock',provider=provider,unified=True,execution_id=plan_id)
        plans=self.server.store.task_plans
        self.assertTrue(all(s['state']=='completed' for s in plans.get(plan_id)['steps']))
        self.assertTrue(any(e['payload'].get('code')=='PLAN_UNCERTAIN_EFFECTS' for e in ws.messages))
        await self.server.handle_message(ws,{'type':'plan.operation.review','thread_id':self.thread.id,'payload':{'plan_id':plan_id,'call_id':'unconfirmed-call','confirm_workspace':True}},set())
        self.server.provider=ScriptedProvider([final_step('已核对现状，完成中文交付。'),final_step('验证完成。')])
        self.server.ensure_model_available=AsyncMock(return_value=True)
        await self.server.handle_message(ws,{'type':'turn.start','thread_id':self.thread.id,'payload':{'prompt':'继续','model':'mock','unified':True,'resume_run_id':plan_id,'confirm_workspace':True}},set())
        await asyncio.wait_for(asyncio.gather(*list(self.server.active_turns.values())),30)
        saved=json.loads(self.server.store.connection.execute('SELECT data_json FROM agent_execution_runs WHERE id=?',(plan_id,)).fetchone()[0])
        self.assertEqual(saved['unified']['phase'],'completed',str(ws.messages[-3:]))
        self.assertEqual(saved['unified']['id'],plan_id)
        self.assertEqual(saved['unified']['plan_id'],plan_id)
        self.assertEqual(len(plans.list_for_thread(self.thread.id)),1)
        self.assertTrue(all(s['state']=='completed' for s in plans.get(plan_id)['steps']))

    async def test_running_followup_is_applied_once_after_tool_batch(self):
        entered,release=asyncio.Event(),asyncio.Event()
        class BlockingSocket(FakeWebSocket):
            async def send_json(socket,message):
                await super().send_json(message)
                if message['type']=='tool.started' and not entered.is_set():
                    entered.set()
                    await release.wait()
        ws=BlockingSocket()
        class InspectingProvider(ScriptedProvider):
            async def stream_chat(provider,**kwargs):
                if provider.calls>=len(provider.steps):
                    raise AssertionError('Unexpected request: '+str(kwargs['messages'][-3:]))
                async for chunk in super().stream_chat(**kwargs):yield chunk
        provider=InspectingProvider([
            tool_step('write_file',{'path':'calculator.py','content':'def add(a,b): return a+b\n'}),
            final_step('计算器修复完成，继续追加步骤。'),
            tool_step('write_file',{'path':'SECOND.md','content':'追加需求已执行\n'}),
            final_step('计算器已修复，新增文档。'),
        ])
        run=asyncio.create_task(self.server.run_tool_turn(ws,thread_id=self.thread.id,turn_id='append-run',prompt='请修复计算器函数',model='mock',provider=provider,unified=True))
        self.server.active_turns['append-run']=run
        self.server.active_turn_threads['append-run']=self.thread.id
        try:
            await asyncio.wait_for(entered.wait(),10)
            request={'type':'turn.append','request_id':'append-request','thread_id':self.thread.id,'turn_id':'append-run',
                     'payload':{'message_id':'followup-1','prompt':'增加 SECOND.md 中文说明'}}
            await self.server.handle_message(ws,request,{'append-run'})
            await self.server.handle_message(ws,request,{'append-run'})
            self.assertEqual(len(self.server.runtime_ledger.pending('append-run')),1)
            self.assertEqual(sum(m['content']=='增加 SECOND.md 中文说明' for m in self.fixture.project.state.get_messages(self.thread.id)),1)
        finally:
            release.set()
            await asyncio.wait_for(run,30)
        self.assertEqual((self.repo/'SECOND.md').read_text(encoding='utf-8'),'追加需求已执行\n')
        self.assertEqual(self.server.runtime_ledger.pending('append-run'),[])
        self.assertEqual(sum(m['type']=='turn.followup.applied' for m in ws.messages),1)
        results=[m['payload']['runtime'] for m in ws.messages if m['type']=='agent.runtime.updated']
        self.assertEqual(results[-1]['outcome'],'completed_verified')
        self.assertEqual(provider.calls,4)

    async def test_cancelled_run_rejects_followup_without_new_model_request(self):
        entered=asyncio.Event()
        class BlockedProvider(ScriptedProvider):
            async def stream_chat(provider,**kwargs):
                provider.calls+=1
                entered.set()
                await asyncio.Event().wait()
                yield final_step()
        provider=BlockedProvider([])
        ws=FakeWebSocket()
        run=asyncio.create_task(self.server.run_tool_turn(ws,thread_id=self.thread.id,turn_id='cancel-run',prompt='请解释 Python 装饰器',model='mock',provider=provider,unified=True))
        self.server.active_turns['cancel-run']=run
        self.server.active_turn_threads['cancel-run']=self.thread.id
        await asyncio.wait_for(entered.wait(),10)
        await self.server.handle_message(ws,{'type':'turn.cancel','turn_id':'cancel-run','thread_id':self.thread.id,'payload':{}},{'cancel-run'})
        await asyncio.gather(run,return_exceptions=True)
        await self.server.handle_message(ws,{'type':'turn.append','turn_id':'cancel-run','thread_id':self.thread.id,'payload':{'message_id':'late-message','prompt':'继续修改'}},{'cancel-run'})
        self.assertTrue(any(m['payload'].get('code')=='FOLLOWUP_REJECTED' for m in ws.messages))
        self.assertEqual(provider.calls,1)
        self.assertEqual(self.server.runtime_ledger.pending('cancel-run'),[])
        events=self.server.runtime_ledger.events(run_id='cancel-run')
        self.assertEqual([e['metadata']['phase'] for e in events if e['kind']=='execution.transition'][-1],'cancelled')

    async def test_unplanned_failed_run_resumes_original_goal_and_budget_via_rpc(self):
        class OfflineProvider(ScriptedProvider):
            async def stream_chat(provider,**kwargs):
                raise ProviderError('MODEL_TIMEOUT','测试连接中断')
                yield final_step()
        await self.server.run_tool_turn(FakeWebSocket(),thread_id=self.thread.id,turn_id='original-run',prompt='请解释 Python 装饰器',model='mock',provider=OfflineProvider([]),unified=True)
        original=json.loads(self.server.store.connection.execute('SELECT data_json FROM agent_execution_runs WHERE id=?',('original-run',)).fetchone()[0])
        self.assertEqual(original['unified']['phase'],'failed')
        self.assertEqual(self.server.store.task_plans.list_for_thread(self.thread.id),[])
        config=self.server.tasks.settings();config['budget']['api_calls']=0
        self.server.store.set_setting('orchestration.config',json.dumps(config))
        provider=ScriptedProvider([final_step('装饰器包装函数以增加行为')])
        self.server.provider=provider
        self.server.ensure_model_available=AsyncMock(return_value=True)
        ws=FakeWebSocket()
        await self.server.handle_message(ws,{'type':'turn.start','thread_id':self.thread.id,'payload':{
            'prompt':'此字段不能替换原始目标','model':'mock','unified':True,'resume_run_id':'original-run','confirm_workspace':True}},set())
        tasks=list(self.server.active_turns.values())
        self.assertEqual(len(tasks),1,str(ws.messages))
        await asyncio.wait_for(asyncio.gather(*tasks),20)
        restored=json.loads(self.server.store.connection.execute('SELECT data_json FROM agent_execution_runs WHERE id=?',('original-run',)).fetchone()[0])
        self.assertEqual(restored['unified']['phase'],'completed',str(ws.messages))
        self.assertEqual(restored['unified_goal'],original['unified_goal'])
        self.assertEqual(restored['unified_config'],original['unified_config'])
        self.assertEqual(restored['calls'],original['calls']+1)
        self.assertEqual(restored['recovery_count'],1)

    async def test_real_backend_process_crash_preserves_reservation_on_restart(self):
        ready=self.fixture.root/'child-ready'
        script='''
import asyncio,sys
from pathlib import Path
from agent.server.main import AgentServer
class Socket:
 async def send_json(self,event):pass
class Provider:
 provider_name='fake'
 context_window=32768
 async def stream_chat(self,**kwargs):
  Path(sys.argv[2]).write_text('ready')
  await asyncio.Event().wait()
  yield
async def main():
 server=AgentServer('test')
 await server.run_tool_turn(Socket(),thread_id=sys.argv[1],turn_id='crash-run',prompt='请解释 Python 装饰器',model='mock',provider=Provider(),unified=True)
asyncio.run(main())
'''
        child=subprocess.Popen([sys.executable,'-c',script,self.thread.id,str(ready)],cwd=str(__import__('pathlib').Path(__file__).resolve().parents[1]),
            env={**os.environ,'PYTHONUTF8':'1'},stdout=subprocess.DEVNULL,stderr=subprocess.PIPE,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
        try:
            for _ in range(200):
                if ready.exists() or child.poll() is not None:break
                await asyncio.sleep(.05)
            self.assertTrue(ready.exists(),'受控后端未进入模型等待')
            before=json.loads(self.server.store.connection.execute('SELECT data_json FROM agent_execution_runs WHERE id=?',('crash-run',)).fetchone()[0])
            self.assertEqual(before['unified']['phase'],'executing')
            self.assertEqual(before['unified_api_requests'][0]['status'],'reserved')
        finally:
            if child.poll() is None:child.kill()
            await asyncio.to_thread(child.communicate,timeout=5)
        await self.server.close_async();self.server.close()
        self.server=AgentServer('test');self.fixture.server=self.server
        after=json.loads(self.server.store.connection.execute('SELECT data_json FROM agent_execution_runs WHERE id=?',('crash-run',)).fetchone()[0])
        self.assertEqual(after['unified']['phase'],'paused')
        self.assertEqual(after['unified']['error_code'],'BACKEND_INTERRUPTED')
        for key in ('calls','reserved_tokens','unified_config','unified_goal'):
            self.assertEqual(after[key],before[key])
        self.assertEqual(after['unified_api_requests'][0]['status'],'interrupted')
        self.assertEqual(self.server.runtime_ledger.recover_executions(),0)
        self.assertEqual(sum(e['kind']=='execution.interrupted' for e in self.server.runtime_ledger.events(run_id='crash-run')),1)

    async def test_concurrent_start_accepts_one_run_only(self):
        entered,release,model_started=asyncio.Event(),asyncio.Event(),asyncio.Event()
        async def availability(*args,**kwargs):
            entered.set();await release.wait();return True
        class BlockedProvider(ScriptedProvider):
            async def stream_chat(provider,**kwargs):
                provider.calls+=1;model_started.set()
                await asyncio.Event().wait()
                yield final_step()
        provider=BlockedProvider([]);self.server.provider=provider
        self.server.ensure_model_available=availability
        ws=FakeWebSocket();owned=set()
        request={'type':'turn.start','thread_id':self.thread.id,'payload':{'prompt':'请解释 Python 装饰器','model':'mock','unified':True}}
        first=asyncio.create_task(self.server.handle_message(ws,{**request,'request_id':'start-a'},owned))
        await asyncio.wait_for(entered.wait(),2)
        second=asyncio.create_task(self.server.handle_message(ws,{**request,'request_id':'start-b'},owned))
        release.set()
        await asyncio.gather(first,second)
        await asyncio.wait_for(model_started.wait(),10)
        self.assertEqual(len(self.server.active_turns),1)
        self.assertTrue(any(m['payload'].get('code')=='TURN_RUNNING' and m.get('request_id')=='start-b' for m in ws.messages))
        self.assertEqual(provider.calls,1)
        run_id=next(iter(self.server.active_turns));run=self.server.active_turns[run_id]
        await self.server.handle_message(ws,{'type':'turn.cancel','turn_id':run_id,'payload':{}},owned)
        await asyncio.gather(run,return_exceptions=True)

    async def test_explicit_plan_budget_extension_keeps_usage_and_global_caps(self):
        ws=FakeWebSocket()
        provider=ScriptedProvider([tool_step('write_file',{'path':'calculator.py','content':'def add(a,b): return a+b\n'}),final_step('真实修复完成')])
        await self.server.run_tool_turn(ws,thread_id=self.thread.id,turn_id='extend-run',prompt='请修复 calculator.py 加法',model='mock',provider=provider,unified=True)
        plan=self.server.store.task_plans.list_for_thread(self.thread.id)[0]
        def saved():return json.loads(self.server.store.connection.execute('SELECT data_json FROM agent_execution_runs WHERE id=?',(plan['id'],)).fetchone()[0])
        before=saved();settings=self.server.tasks.settings()
        await self.server.handle_message(ws,{'type':'plan.execution.extend','thread_id':self.thread.id,'payload':{'plan_id':plan['id']}},set())
        after=saved()
        for key in ('calls','reserved_tokens','unified_api_requests'):
            self.assertEqual(after[key],before[key])
        self.assertEqual(after['unified_config']['budget']['api_tokens'],before['unified_config']['budget']['api_tokens']+500000)
        self.assertEqual(after['unified_config']['budget']['api_calls'],before['unified_config']['budget']['api_calls']+16)
        for key in ('global_api_tokens','global_api_calls','api_cost','global_api_cost'):
            self.assertEqual(after['unified_config']['budget'][key],before['unified_config']['budget'][key])
        self.assertEqual(self.server.tasks.settings(),settings)
        await self.server.handle_message(ws,{'type':'plan.execution.extend','thread_id':self.thread.id,'payload':{'plan_id':plan['id'],'include_global':True}},set())
        global_update=saved()
        self.assertEqual(global_update['unified_config']['budget']['global_api_tokens'],after['unified_config']['budget']['global_api_tokens']+500000)
        self.assertEqual(global_update['unified_config']['budget']['global_api_calls'],after['unified_config']['budget']['global_api_calls']+16)
        self.assertEqual(global_update['unified_api_requests'],before['unified_api_requests'])
        self.assertEqual(self.server.tasks.settings(),settings)
