import asyncio
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import tempfile
import unittest
from unittest.mock import patch,AsyncMock

from agent.core.unified_runtime import infer_intent, verification_policy, result_view, workspace_snapshot,requested_intent
from agent.llm.router import validate_config
from agent.server.main import AgentServer
from agent.task_plans import TaskPlanStore
from test_agent_reliability import FakeWebSocket, ScriptedProvider, final_step, tool_step


class UnifiedPolicyTests(unittest.TestCase):
    def test_request_shape_is_refined_by_tools_and_respects_read_only(self):
        self.assertEqual(requested_intent('Python 装饰器是什么？')['kind'],'question')
        self.assertEqual(requested_intent('请解释如何修改 Python 代码')['kind'],'question')
        self.assertEqual(requested_intent('把登录按钮文字改成中文')['kind'],'change')
        self.assertEqual(requested_intent('只返回 JSON，不读取或修改工程')['kind'],'question')
        self.assertTrue(requested_intent('只分析启动失败，不修改任何文件')['read_only'])
        self.assertEqual(requested_intent('实现以下要求\n1. 创建核心模块\n2. 编写测试\n3. 生成交付报告')['kind'],'complex')

    def test_intent_uses_model_plan_and_actual_evidence_not_words(self):
        self.assertEqual(infer_intent('question','read_file',read_only=True),'analysis')
        self.assertEqual(infer_intent('analysis','write_file',changed_paths=['x.py']),'change')
        self.assertEqual(infer_intent('change','agent_plan'),'complex')
        self.assertEqual(infer_intent('change','write_file',changed_paths=['a','b','c']),'complex')
        self.assertEqual(infer_intent('complex','read_file'),'complex')

    def test_verification_levels_do_not_invent_test_tools(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);(root/'x.py').write_text('x=1')
            self.assertEqual(verification_policy(root,[])['level'],'none')
            self.assertEqual(verification_policy(root,['x.py'])['level'],'basic')
            self.assertEqual(verification_policy(root,['README.md'])['level'],'manual')
            self.assertEqual(verification_policy(root,['x.py'],override='none')['commands'],[])
            self.assertEqual(verification_policy(root,['x.py'],override='manual')['level'],'manual')
            (root/'package.json').write_text('{"scripts":{"typecheck":"tsc --noEmit","test":"vitest run"}}')
            self.assertEqual(verification_policy(root,['x.py'])['level'],'targeted')
            self.assertEqual(verification_policy(root,['x.py'],override='full')['level'],'full')

    def test_shell_path_encoding_does_not_interpolate_filenames(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);name="odd'$value.py";(root/name).write_text('x=1')
            command=verification_policy(root,[name])['commands'][0]
            self.assertNotIn(name,command)
            self.assertIn('base64.b64decode',command)

    def test_nested_package_paths_cannot_expand_shell_code(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);folder=root/'bad$(echo hidden)';folder.mkdir()
            (folder/'package.json').write_text('{"scripts":{"typecheck":"tsc --noEmit","test":"node test.js"}}')
            with self.assertRaises(ValueError):verification_policy(root,[folder.name+'/a.ts'])

    def test_typescript_without_type_checker_is_manual_not_a_false_pass(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);(root/'package.json').write_text('{"scripts":{"test":"node test.js"}}')
            result=verification_policy(root,['src/a.ts'])
            self.assertEqual(result['level'],'manual');self.assertEqual(result['commands'],[])
            self.assertIn('TypeScript',result['reason'])

    def test_result_cannot_trust_model_claims_or_diff_only(self):
        self.assertEqual(result_view(changed=True,results=[]),'completed_unverified')
        self.assertEqual(result_view(changed=True,results=[{'ok':False,'category':'environment'}]),'awaiting_user')
        self.assertEqual(result_view(changed=True,results=[{'ok':True}],pending=True),'partially_completed')
        self.assertEqual(result_view(changed=True,results=[{'ok':True}],level='targeted'),'completed_verified')
        self.assertEqual(result_view(changed=True,results=[],status='cancelled'),'cancelled')

    def test_upgrade_preserves_completed_steps_and_journal(self):
        db=sqlite3.connect(':memory:');store=TaskPlanStore(db)
        pid=store.create('t','goal',[{'description':'Original'}]);step=store.get(pid)['steps'][0]
        store.update_step(pid,step['id'],'completed',[{'tool':'write_file','ok':True}])
        store.append_steps(pid,[{'description':'New scope'}])
        self.assertEqual(store.get(pid)['steps'][0]['state'],'completed')
        self.assertEqual(store.get(pid)['steps'][0]['id'],step['id'])
        self.assertEqual(len(store.get(pid)['steps']),2)
        db.close()

    def test_snapshot_detects_shell_writes_and_deletes_not_dependencies(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);(root/'node_modules').mkdir();(root/'node_modules/a').write_text('ignored')
            (root/'x.py').write_text('a=1');before=workspace_snapshot(root)
            (root/'x.py').unlink();(root/'new.py').write_text('a=2')
            after=workspace_snapshot(root)
            self.assertIn('x.py',before);self.assertNotIn('x.py',after)
            self.assertIn('new.py',after);self.assertNotIn('node_modules/a',after)


class UnifiedLoopTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name);self.repo=self.root/'repo';self.repo.mkdir()
        self.env=patch.dict(os.environ,{'LCA_DATA_DIR':str(self.root/'data')});self.env.start()
        (self.repo/'calculator.py').write_text('def add(a,b): return a-b\n')
        (self.repo/'tests').mkdir();(self.repo/'tests/test_calc.py').write_text('import unittest\nfrom calculator import add\nclass Calc(unittest.TestCase):\n def test_add(self): self.assertEqual(add(3,2),5)\n')
        (self.repo/'.gitignore').write_text('__pycache__/\n.venv/\n')
        for args in (['init','-q'],['config','user.name','Test'],['config','user.email','test@example.test'],['add','.'],['commit','-qm','fixture']):
            subprocess.run(['git',*args],cwd=self.repo,capture_output=True,check=True)
        self.server=AgentServer('test');self.project,self.thread,_=self.server.projects.open(str(self.repo),active_model='test')
        self.ws=FakeWebSocket()
        async def approve(*a,**kw):return 'allow_once'
        self.server.approvals.request=approve
        self.server.store.set_setting('orchestration.config',json.dumps(validate_config({'verification_commands':['uv run --no-project python -m unittest discover -s tests -v']})))

    async def asyncTearDown(self):
        await self.server.close_async();self.server.close();self.env.stop();self.temp.cleanup()

    async def run_steps(self,steps):
        provider=ScriptedProvider(steps)
        await self.server.run_tool_turn(self.ws,thread_id=self.thread.id,turn_id='unified-test',prompt='按照实际需求完成工作',model='mock',provider=provider,unified=True)
        updates=[x['payload']['runtime'] for x in self.ws.messages if x['type']=='agent.runtime.updated']
        return provider,updates[-1]

    async def test_question_has_no_plan_or_tools(self):
        p,r=await self.run_steps([final_step('装饰器包装函数以增加行为')])
        self.assertEqual(p.calls,1);self.assertEqual(r['intent'],'question')
        self.assertEqual(self.server.store.task_plans.list_for_thread(self.thread.id),[])
        self.assertEqual(r['verification'],[])

    async def test_prose_only_development_cannot_complete_or_loop_forever(self):
        p=ScriptedProvider([final_step('这里是代码示例'),final_step('仍然只有示例')])
        await self.server.run_tool_turn(self.ws,thread_id=self.thread.id,turn_id='prose-only',prompt='请实现真实的代码修改',model='mock',provider=p,unified=True)
        self.assertEqual(p.calls,2)
        self.assertTrue(any(e['type']=='turn.failed' and e['payload'].get('code')=='AGENT_NO_CHANGE_EVIDENCE' for e in self.ws.messages))
        self.assertIn('a-b',(self.repo/'calculator.py').read_text())

    async def test_read_only_user_intent_blocks_model_mutation(self):
        p=ScriptedProvider([tool_step('write_file',{'path':'calculator.py','content':'wrong'})])
        await self.server.run_tool_turn(self.ws,thread_id=self.thread.id,turn_id='read-only-request',prompt='只分析程序，不修改任何文件',model='mock',provider=p,unified=True)
        self.assertIn('a-b',(self.repo/'calculator.py').read_text())
        self.assertTrue(any(e['type']=='turn.failed' and e['payload'].get('code')=='UNIFIED_READ_ONLY_INTENT' for e in self.ws.messages))

    async def test_concept_question_exposes_no_tools_and_rejects_invented_tool_calls(self):
        class QuestionProvider(ScriptedProvider):
            async def stream_chat(self,**kwargs):
                self_outer.assertIsNone(kwargs.get('tools'))
                async for chunk in super().stream_chat(**kwargs):yield chunk
        self_outer=self
        p=QuestionProvider([tool_step('write_file',{'path':'calculator.py','content':'bad'})])
        await self.server.run_tool_turn(self.ws,thread_id=self.thread.id,turn_id='concept-question',prompt='请解释 Python 装饰器',model='mock',provider=p,unified=True)
        self.assertIn('a-b',(self.repo/'calculator.py').read_text())
        self.assertEqual(self.server.store.task_plans.list_for_thread(self.thread.id),[])
        self.assertTrue(any(e['type']=='turn.failed' and e['payload'].get('code')=='UNIFIED_QUESTION_TOOLS' for e in self.ws.messages))

    async def test_read_only_analysis_has_no_development_plan(self):
        _,r=await self.run_steps([tool_step('read_file',{'path':'calculator.py'}),final_step('减法导致错误')])
        self.assertEqual(r['intent'],'analysis');self.assertEqual(r['changed_paths'],[])
        self.assertEqual(self.server.store.task_plans.list_for_thread(self.thread.id),[])

    async def test_edit_automatically_runs_real_unittest_and_diff_without_model_command(self):
        p,r=await self.run_steps([tool_step('write_file',{'path':'calculator.py','content':'def add(a,b): return a+b\n'}),final_step('已修改')])
        self.assertEqual(p.calls,2);self.assertEqual(r['outcome'],'completed_verified')
        self.assertTrue(r['verification'][0]['ok']);self.assertIn('Ran 1 test',r['verification'][0]['summary'])
        self.assertTrue(Path(r['verification'][0]['log_path']).is_file())
        self.assertIn('calculator.py',r['changed_paths'])

    async def test_real_failed_independent_test_is_repaired_then_verified(self):
        p,r=await self.run_steps([tool_step('write_file',{'path':'calculator.py','content':'def add(a,b): return a*b\n'}),final_step('声称通过不是证据'),tool_step('write_file',{'path':'calculator.py','content':'def add(a,b): return a+b\n'}),final_step('修复完成')])
        self.assertEqual(p.calls,4);self.assertEqual(r['repairs'],1);self.assertEqual(r['outcome'],'completed_verified')
        self.assertTrue(any(x['payload']['runtime']['phase']=='repairing' for x in self.ws.messages if x['type']=='agent.runtime.updated'))

    async def test_missing_dependency_stops_without_another_model_request(self):
        self.server.store.set_setting('orchestration.config',json.dumps(validate_config({'verification_commands':['uv run --no-project python -c "import lca_missing_dependency_01234"']})))
        p,r=await self.run_steps([tool_step('write_file',{'path':'calculator.py','content':'def add(a,b): return a+b\n'}),final_step('完成')])
        self.assertEqual(p.calls,2);self.assertEqual(r['outcome'],'awaiting_user')
        self.assertEqual(r['verification'][0]['category'],'environment')
        self.assertEqual(r['verification'][0]['exit_code'],1)

    async def test_explicit_zero_budget_sends_no_request(self):
        self.server.store.set_setting('orchestration.config',json.dumps(validate_config({'budget':{'api_calls':0}})))
        p,r=await self.run_steps([final_step('must not be called')])
        self.assertEqual(p.calls,0);self.assertEqual(r['phase'],'failed')

    async def test_complex_model_plan_persists_and_completes_using_real_evidence(self):
        _,r=await self.run_steps([tool_step('agent_plan',{'steps':[{'description':'Inspect and fix'}]}),tool_step('read_file',{'path':'calculator.py'}),tool_step('write_file',{'path':'calculator.py','content':'def add(a,b): return a+b\n'}),final_step('交付完成')])
        self.assertEqual(r['intent'],'complex');self.assertEqual(r['outcome'],'completed_verified')
        plan=self.server.store.task_plans.get(r['plan_id'])
        self.assertEqual(plan['steps'][0]['state'],'completed')
        self.assertGreater(len(self.server.store.task_plans.executions(r['plan_id'])),0)

    async def test_restart_snapshot_api_returns_real_persisted_result(self):
        _,r=await self.run_steps([final_step('回答')])
        ws=FakeWebSocket()
        await self.server.tasks.handle(ws,{'type':'task.runtime.list','thread_id':self.thread.id,'payload':{}},set())
        self.assertEqual(ws.messages[-1]['payload']['runtimes'][0]['id'],r['id'])

    async def test_bad_project_verification_config_is_specific_unverified_result(self):
        self.server.store.set_setting('orchestration.config',json.dumps(validate_config({})))
        (self.repo/'.lca').mkdir();(self.repo/'.lca/verification.json').write_text('invalid json')
        p,r=await self.run_steps([tool_step('write_file',{'path':'calculator.py','content':'def add(a,b): return a+b\n'}),final_step('完成')])
        self.assertEqual(p.calls,2);self.assertEqual(r['outcome'],'awaiting_user')
        self.assertEqual(r['verification'][0]['category'],'configuration')

    async def test_api_cost_cap_without_prices_prevents_first_request(self):
        self.server.store.set_setting('orchestration.config',json.dumps(validate_config({'budget':{'api_cost':1}})))
        p,r=await self.run_steps([final_step('must not run')])
        self.assertEqual(p.calls,0);self.assertIn('prices',r['reason'])

    async def test_unified_requests_count_toward_original_global_budget(self):
        p,r=await self.run_steps([final_step('回答')])
        self.assertEqual(self.server.tasks.runtime.usage()['api_calls'],1)
        from agent.core.budget import BudgetGuard,BudgetExceeded
        task=self.server.tasks.runtime.create(self.thread.id,'Legacy task',validate_config({}),'workspace')
        guard=BudgetGuard(self.server.tasks.runtime,task['id'],validate_config({'budget':{'global_api_calls':1}})['budget'])
        with self.assertRaises(BudgetExceeded):
            guard.reserve(route='api',role='executor',model='mock',messages=[{'role':'user','content':'goal'}],tools=None,context_window=65536,output_limit=100)

    async def test_cancellation_and_resume_keep_budget_baseline_and_completed_effects(self):
        class EditThenBlock(ScriptedProvider):
            def __init__(self):
                super().__init__([tool_step('write_file',{'path':'calculator.py','content':'def add(a,b): return a+b\n'})]);self.waiting=asyncio.Event()
            async def stream_chat(self,**kwargs):
                if self.calls==0:
                    async for chunk in super().stream_chat(**kwargs):yield chunk
                else:
                    self.waiting.set();await asyncio.sleep(30)
        p=EditThenBlock()
        turn=asyncio.create_task(self.server.run_tool_turn(self.ws,thread_id=self.thread.id,turn_id='interrupt',prompt='Fix addition',model='mock',provider=p,unified=True))
        await asyncio.wait_for(p.waiting.wait(),10);turn.cancel()
        with self.assertRaises(asyncio.CancelledError):await turn
        plan=self.server.store.task_plans.list_for_thread(self.thread.id)[0]
        original=[x for x in self.server.store.task_plans.executions(plan['id']) if x['tool']=='write_file' and x['status']=='succeeded']
        before=self.server.tasks.runtime.usage()['api_calls']
        self.server.store.set_setting('orchestration.config',json.dumps(validate_config({'budget':{'api_calls':0}})))
        await self.server.handle_message(self.ws,{'type':'plan.recover','thread_id':self.thread.id,'payload':{'plan_id':plan['id']}},set())
        provider=ScriptedProvider([tool_step('read_file',{'path':'calculator.py'}),final_step('已检查原修改并验证')])
        self.server.provider=provider;self.server.ensure_model_available=AsyncMock(return_value=True)
        await self.server.handle_message(self.ws,{'type':'turn.start','thread_id':self.thread.id,'payload':{'prompt':'恢复原任务','model':'mock','unified':True}},set())
        await asyncio.gather(*self.server.active_turns.values())
        r=[x['payload']['runtime'] for x in self.ws.messages if x['type']=='agent.runtime.updated'][-1]
        self.assertEqual(provider.calls,2)
        self.assertEqual(r['outcome'],'completed_verified')
        self.assertEqual(r['plan_id'],plan['id'])
        self.assertEqual([x for x in self.server.store.task_plans.executions(plan['id']) if x['tool']=='write_file' and x['status']=='succeeded'],original)
        self.assertEqual(self.server.tasks.runtime.usage()['api_calls'],before+2)

    async def test_three_file_scope_upgrades_with_existing_evidence(self):
        _,r=await self.run_steps([tool_step('write_file',{'path':'calculator.py','content':'def add(a,b): return a+b\n'}),tool_step('write_file',{'path':'a.py','content':'a=1\n'}),tool_step('write_file',{'path':'b.py','content':'b=2\n'}),final_step('完成')])
        self.assertEqual(r['intent'],'complex');self.assertEqual(r['outcome'],'completed_verified')
        self.assertEqual(len([x for x in self.server.store.task_plans.executions(r['plan_id']) if x['tool']=='write_file']),3)

    async def test_paused_plan_does_not_block_question_or_allow_unconfirmed_mutation(self):
        pid=self.server.store.task_plans.create(self.thread.id,'Original goal',[{'description':'Pending change'}])
        step=self.server.store.task_plans.get(pid)['steps'][0]
        self.server.store.task_plans.update_step(pid,step['id'],'in_progress')
        self.server.store.task_plans.update_step(pid,step['id'],'blocked')
        provider=ScriptedProvider([final_step('装饰器解释')])
        await self.server.run_tool_turn(self.ws,thread_id=self.thread.id,turn_id='question-while-blocked',prompt='解释装饰器',model='mock',provider=provider,unified=True,deferred_plan_ids=[pid])
        self.assertEqual(self.server.store.task_plans.get(pid)['steps'][0]['state'],'blocked')
        self.assertTrue(any(e['type']=='turn.completed' and e['turn_id']=='question-while-blocked' for e in self.ws.messages))
        mutator=ScriptedProvider([tool_step('write_file',{'path':'calculator.py','content':'UNAUTHORIZED'})])
        await self.server.run_tool_turn(self.ws,thread_id=self.thread.id,turn_id='blocked-write',prompt='Change it',model='mock',provider=mutator,unified=True,deferred_plan_ids=[pid])
        self.assertIn('a-b',(self.repo/'calculator.py').read_text())
        self.assertTrue(any(e['type']=='turn.failed' and e['payload'].get('code')=='PLAN_RESUME_CONFIRMATION_REQUIRED' for e in self.ws.messages))

    async def test_text_only_model_answers_without_tool_schemas(self):
        class TextOnly(ScriptedProvider):
            agent_tools_enabled=False
            async def stream_chat(self,**kwargs):
                self_outer.assertIsNone(kwargs.get('tools'))
                async for chunk in super().stream_chat(**kwargs):yield chunk
        self_outer=self
        p=TextOnly([final_step('回答')])
        await self.server.run_tool_turn(self.ws,thread_id=self.thread.id,turn_id='text-only',prompt='问题',model='text-only',provider=p,unified=True)
        self.assertEqual(p.calls,1)
        self.assertEqual(self.server.store.task_plans.list_for_thread(self.thread.id),[])

    async def test_diagnostic_export_is_short_private_and_preserves_evidence(self):
        _,r=await self.run_steps([tool_step('write_file',{'path':'calculator.py','content':'def add(a,b): return a+b\n'}),final_step('完成')])
        before=self.server.store.task_plans.executions(r['plan_id'])
        ws=FakeWebSocket()
        await self.server.tasks.handle(ws,{'type':'task.runtime.diagnostics','thread_id':self.thread.id,'payload':{'run_id':r['id']}},set())
        output=ws.messages[-1]['payload']
        self.assertLessEqual(len(output['markdown'].splitlines()),150)
        self.assertTrue(Path(output['json_path']).is_file())
        value=json.loads(Path(output['json_path']).read_text(encoding='utf-8'))
        self.assertEqual(len(value['executions']),len(before))
        self.assertNotIn('goal',value['plan'])
        self.assertNotIn('stdout',value['runtime']['verification'][0])
        self.assertEqual(self.server.store.task_plans.executions(r['plan_id']),before)

    async def test_real_protocol_preflight_rejects_zero_before_turn_started(self):
        self.server.ensure_model_available=AsyncMock(return_value=True)
        self.server.provider=ScriptedProvider([final_step('not sent')])
        self.server.store.set_setting('orchestration.config',json.dumps(validate_config({'budget':{'api_calls':0}})))
        await self.server.handle_message(self.ws,{'type':'turn.start','thread_id':self.thread.id,'payload':{'prompt':'question','model':'mock','unified':True}},set())
        self.assertEqual(self.server.provider.calls,0)
        self.assertFalse(any(e['type']=='turn.started' for e in self.ws.messages))
        self.assertIn('api_calls',self.ws.messages[-1]['payload']['message'])
        self.assertEqual(self.project.state.get_messages(self.thread.id),[])

    async def test_intermediate_step_does_not_run_future_module_tests_but_final_does(self):
        (self.repo/'tests/test_future.py').write_text('import unittest\nimport newmodule\nclass Future(unittest.TestCase):\n def test_future(self): self.assertTrue(newmodule.ready())\n')
        _,r=await self.run_steps([tool_step('agent_plan',{'steps':[{'description':'Repair current calculator'},{'description':'Implement the future module and verify the whole project'}]}),tool_step('write_file',{'path':'calculator.py','content':'def add(a,b): return a+b\n'}),final_step('当前步骤代码已修改'),tool_step('write_file',{'path':'newmodule.py','content':'def ready(): return True\n'}),final_step('完成全部实现')])
        self.assertEqual(r['outcome'],'completed_verified')
        self.assertTrue(all(s['state']=='completed' for s in r['plan']['steps']))
        row=self.server.store.connection.execute('SELECT data_json FROM agent_execution_runs WHERE id=?',(r['id'],)).fetchone()
        history=json.loads(row[0])['unified_verification_history']
        self.assertEqual(history[0]['level'],'basic')
        self.assertIn('unittest',history[-1]['results'][0]['command'])
        self.assertTrue(history[-1]['results'][0]['ok'])

    async def test_real_protocol_persists_one_user_message_not_two(self):
        self.server.ensure_model_available=AsyncMock(return_value=True)
        self.server.provider=ScriptedProvider([final_step('Answer')])
        await self.server.handle_message(self.ws,{'type':'turn.start','thread_id':self.thread.id,'payload':{'prompt':'Question','model':'mock','unified':True}},set())
        await asyncio.gather(*self.server.active_turns.values())
        messages=self.project.state.get_messages(self.thread.id)
        self.assertEqual([m['role'] for m in messages],['user','assistant'])
        self.assertEqual(messages[0]['content'],'Question')

    async def test_websocket_disconnect_keeps_server_owned_mcp_and_records_pause(self):
        from aiohttp import web
        from aiohttp.test_utils import TestClient,TestServer
        self.server.mcp_runtime.close=AsyncMock()
        app=web.Application();app.router.add_get('/ws',self.server.websocket)
        async with TestClient(TestServer(app)) as client:
            ws=await client.ws_connect('/ws',headers={'Authorization':'Bearer test'})
            await ws.receive_json();await ws.close();await asyncio.sleep(.05)
        self.server.mcp_runtime.close.assert_not_awaited()

    async def test_frozen_profile_uses_original_endpoint_model_timeout_and_prices(self):
        provider=ScriptedProvider([])
        self.server.tasks.provider_factory_override=lambda route,profile:provider
        snapshot={'profile':{'model_profile_id':'original','route':'api','model':'original-model','output_limit':1024,'input_price':1,'output_price':2,
                             '_connection':{'connection_id':'old','credential_reference':'fixture'}},'capabilities':{'text':'PASS','tools':'PASS'},'request_seconds':17}
        with patch.object(self.server.tasks,'catalog',side_effect=AssertionError('Snapshot restoration must not read a changed catalog')):
            restored,model=self.server.chat_provider('profile:original',snapshot)
        self.assertEqual(model,'original-model');self.assertEqual(restored.request_timeout,17)
        self.assertEqual(restored.billing_prices,{'input_price':1,'output_price':2})

    async def test_active_websocket_loss_persists_pause_usage_and_clears_running_ids(self):
        from aiohttp import web
        from aiohttp.test_utils import TestClient,TestServer
        from test_agent_reliability import BlockingProvider
        provider=BlockingProvider();self.server.provider=provider
        self.server.ensure_model_available=AsyncMock(return_value=True)
        app=web.Application();app.router.add_get('/ws',self.server.websocket)
        async with TestClient(TestServer(app)) as client:
            ws=await client.ws_connect('/ws',headers={'Authorization':'Bearer test'});await ws.receive_json()
            await ws.send_json({'type':'turn.start','thread_id':self.thread.id,'payload':{'model':'mock','prompt':'真实连接中断测试','unified':True}})
            await asyncio.wait_for(provider.started.wait(),10)
            await ws.close()
            for _ in range(100):
                if not self.server.active_turns:break
                await asyncio.sleep(.02)
        ws=FakeWebSocket();await self.server.tasks.handle(ws,{'type':'task.runtime.list','thread_id':self.thread.id,'payload':{}},set())
        payload=ws.messages[-1]['payload']
        self.assertEqual(payload['active_turn_ids'],[])
        self.assertEqual(payload['runtimes'][0]['phase'],'paused')
        self.assertEqual(payload['runtimes'][0]['outcome'],'awaiting_user')
        self.assertEqual(self.server.tasks.runtime.usage()['api_calls'],1)
        self.assertEqual(self.project.state.get_messages(self.thread.id)[0]['role'],'user')
