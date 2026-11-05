"""真实 HTTP Mock + 原 Runtime/文件/测试/预算；不依赖付费 API。"""
import asyncio
from datetime import datetime,timezone
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time
import unittest
from unittest.mock import patch
from aiohttp import web
from agent.core.model_catalog import KEY,validate_catalog
from agent.core.model_routing import CapabilityRegistry
from agent.permissions.policy import PermissionMode
from agent.server.main import AgentServer
from test_agent_reliability import FakeWebSocket

class RuntimeRoutingTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp=tempfile.TemporaryDirectory();self.base=Path(self.temp.name);self.root=self.base/'repo';self.root.mkdir()
        self.env=patch.dict(os.environ,{'LCA_DATA_DIR':str(self.base/'data')});self.env.start()
        (self.root/'calculator.py').write_text('def add(a,b):\n    return a-b\n')
        (self.root/'tests').mkdir();(self.root/'tests/test_calc.py').write_text('import unittest\nfrom calculator import add\nclass Test(unittest.TestCase):\n def test_add(self): self.assertEqual(add(2,3),5)\n')
        (self.root/'.gitignore').write_text('__pycache__/\n.venv/\n')
        for args in [['init','-q','-b','main'],['config','user.name','Fixture'],['config','user.email','fixture@example.test'],['add','.'],['commit','-qm','baseline']]:subprocess.run(['git',*args],cwd=self.root,check=True,capture_output=True)
        self.requests=[];self.mode='after_write_quota';self.carry=False
        async def handler(request):
            body=await request.json();model=body['model'];self.requests.append(model)
            history=body['messages'];results=[m for m in history if m.get('role')=='tool']
            if self.mode=='memory_rule_only':return self.answer('已处理项目约定。')
            if self.mode=='memory_analysis':
                if not results:return self.tool('knowledge_search',{'query':'add','mode':'symbol'})
                if not any(m.get('name')=='project_memory' for m in results):return self.tool('project_memory',{'action':'save','title':'测试约定','content':'本工程使用 unittest。'})
                return self.answer('已分析项目并保存 unittest 约定，没有修改代码。')
            if self.mode=='all_quota' or model=='a-model' and (self.mode=='quota' or results):return web.json_response({'error':{'code':'AllocationQuota.FreeTierOnly'}},status=403)
            if self.mode=='auth' and model=='a-model':return web.json_response({'error':{'code':'invalid_api_key'}},status=401)
            if self.mode=='rate' and len(self.requests)==1:return web.json_response({'error':{'code':'rate_limit'}},status=429,headers={'Retry-After':'1'})
            if self.mode=='rate':return self.answer('概念回答，未调用工具。')
            if model=='a-model':return self.tool('write_file',{'path':'calculator.py','content':'def add(a,b):\n    return a+b\n'})
            self.carry=any(m.get('name')=='write_file' and json.loads(m['content']).get('ok') for m in results) and any('加法' in str(m.get('content')) for m in history if m['role']=='user')
            if not any(m.get('name')=='write_file' for m in results):return self.tool('write_file',{'path':'calculator.py','content':'def add(a,b):\n    return a+b\n'})
            if not any(m.get('name')=='run_command' for m in results):return self.tool('run_command',{'command':'uv run --no-project python -m unittest discover -s tests -v','timeout_seconds':30})
            if not any(m.get('name')=='git_diff' for m in results):return self.tool('git_diff',{})
            return self.answer('已修改加法，真实 unittest 和差异检查已通过。')
        app=web.Application();app.router.add_post('/v1/chat/completions',handler);self.runner=web.AppRunner(app);await self.runner.setup();site=web.TCPSite(self.runner,'127.0.0.1',0);await site.start();port=site._server.sockets[0].getsockname()[1]
        self.server=AgentServer('test');self.server.permissions.set_mode(PermissionMode.FULL_ACCESS)
        raw=validate_catalog({'connections':[{'connection_id':'mock','display_name':'HTTP Mock','provider_type':'openai_compatible','base_url':f'http://127.0.0.1:{port}/v1','enabled':True,'credential_reference':'connection-mock'}],
            'profiles':[{'model_profile_id':p,'connection_id':'mock','model_id':p+'-model','display_name':p,'context_window':65536,'max_output_tokens':1024} for p in ['a','b']]})
        self.server.store.set_setting(KEY,json.dumps(raw));self.server.tasks.credentials={'connection-mock':'inert-test-value'}
        for p in raw['profiles']:
            self.server.store.set_setting('model.test.'+p['model_profile_id'],json.dumps({'configuration':'PASS','live':True,'text':'PASS','tools':'PASS','vision':'PASS','tested_at':datetime.now(timezone.utc).isoformat(),'config_fingerprint':self.server.tasks.catalog().fingerprint(p['model_profile_id'])}))
        self.project,self.thread,_=self.server.projects.open(self.root,active_model='auto');self.ws=FakeWebSocket()
    async def asyncTearDown(self):
        await self.server.close_async();self.server.close();await self.runner.cleanup();self.env.stop();self.temp.cleanup()
    def answer(self,content):return web.json_response({'choices':[{'message':{'content':content},'finish_reason':'stop'}],'usage':{'prompt_tokens':40,'completion_tokens':20}})
    def tool(self,name,args):return web.json_response({'choices':[{'message':{'content':'','tool_calls':[{'id':'call-'+str(len(self.requests)),'type':'function','function':{'name':name,'arguments':json.dumps(args)}}]},'finish_reason':'tool_calls'}],'usage':{'prompt_tokens':40,'completion_tokens':20}})
    async def start(self,model='auto',prompt='把 calculator.py 的减法修复为加法，并运行 unittest 检查差异',**payload):
        await self.server.handle_message(self.ws,{'type':'turn.start','thread_id':self.thread.id,'payload':{'prompt':prompt,'model':model,'unified':True,**payload}},set())
        await asyncio.gather(*list(self.server.active_turns.values()))
    async def test_auto_fallback_keeps_tool_evidence_and_real_file_test_diff(self):
        await self.start();self.assertEqual(self.requests[:3],['a-model','a-model','b-model']);self.assertTrue(self.carry)
        writes=[e for e in self.ws.messages if e['type']=='tool.completed' and e['payload']['name']=='write_file'];self.assertEqual(len(writes),1)
        self.assertIn('a+b',(self.root/'calculator.py').read_text())
        updates=[e['payload']['runtime'] for e in self.ws.messages if e['type']=='agent.runtime.updated'];last=updates[-1]
        self.assertEqual(last['phase'],'completed',last);self.assertEqual(last['outcome'],'completed_verified');self.assertTrue(last['verification']);self.assertTrue(all(r['ok'] for r in last['verification']))
        self.assertEqual(len(last['routing']['switches']),1);self.assertEqual(last['routing']['switches'][0]['code'],'MODEL_QUOTA_EXHAUSTED')
        diff=subprocess.run(['git','diff','--check'],cwd=self.root,capture_output=True);self.assertEqual(diff.returncode,0)
        self.assertEqual(self.server.tasks.runtime.usage(last['id'])['api_calls'],len(self.requests))
    async def test_manual_quota_never_falls_back_without_permission(self):
        self.mode='quota';await self.start('profile:a');self.assertEqual(self.requests,['a-model'])
        self.assertTrue(any(e['type']=='turn.failed' for e in self.ws.messages))
        self.assertEqual((self.root/'calculator.py').read_text(),'def add(a,b):\n    return a-b\n')
    async def test_project_analysis_and_memory_save_need_no_code_change(self):
        self.mode='memory_analysis'
        await self.start(prompt='检索项目入口，解释关键模块，不修改代码。保存项目记忆。')
        last=[e['payload']['runtime'] for e in self.ws.messages if e['type']=='agent.runtime.updated'][-1]
        self.assertEqual(last['phase'],'completed',last.get('reason'));self.assertEqual(last['intent'],'analysis')
        self.assertFalse(last['changed_paths']);self.assertEqual(self.requests,['a-model']*3)
        self.assertTrue(self.project.knowledge().list('unittest'))
    async def test_literal_user_rule_survives_new_session_even_with_auto_memory_disabled(self):
        from agent.server.projects import ProjectRegistry
        self.project.knowledge().set_auto(False);self.mode='memory_rule_only'
        rule='本工程必须使用 unittest，交付摘要使用中文。'
        await self.start(prompt='只分析项目，不修改代码。记住：'+rule)
        reopened=ProjectRegistry(self.server.store).get(self.project.id)
        records=reopened.knowledge().list()
        self.assertEqual(len(records),1);self.assertEqual(records[0]['content'],rule);self.assertEqual(records[0]['trust'],'user')
        self.assertEqual(len(self.requests),1)
    async def test_long_goal_is_preserved_while_automatic_retrieval_query_is_bounded(self):
        await self.start(prompt='修复 calculator.py 的加法，运行 unittest。补充背景：'+('这是长任务背景。'*100))
        last=[e['payload']['runtime'] for e in self.ws.messages if e['type']=='agent.runtime.updated'][-1]
        self.assertEqual(last['outcome'],'completed_verified',last.get('reason'))
        self.assertEqual(len([e for e in self.ws.messages if e['type']=='tool.completed' and e['payload']['name']=='write_file']),1)
    async def test_manual_explicit_fallback_preserves_original_selection(self):
        self.mode='quota';await self.start('profile:a',allow_model_fallback=True)
        self.assertEqual(self.requests[:2],['a-model','b-model']);self.assertEqual(self.thread.active_model,'profile:a')
        last=[e['payload']['runtime'] for e in self.ws.messages if e['type']=='agent.runtime.updated'][-1]
        self.assertEqual(last['phase'],'completed');self.assertEqual(last['routing']['mode'],'manual')
    async def test_auth_configuration_error_stops_without_rotating(self):
        self.mode='auth';await self.start();self.assertEqual(self.requests,['a-model'])
        self.assertEqual([e for e in self.ws.messages if e['type']=='turn.failed'][-1]['payload']['code'],'OPENAI_COMPATIBLE_AUTH_FAILED')
    async def test_all_unavailable_stops_and_new_auto_task_sends_no_request(self):
        self.mode='all_quota';await self.start();self.assertEqual(self.requests,['a-model','b-model'])
        failure=[e for e in self.ws.messages if e['type']=='turn.failed'][-1];self.assertEqual(failure['payload']['code'],'MODEL_CANDIDATES_EXHAUSTED')
        persisted=json.loads(self.server.store.connection.execute('SELECT data_json FROM agent_execution_runs').fetchone()[0]);self.assertIn('加法',persisted['unified_goal']);self.assertEqual(len(persisted['model_routing']['tried']),2)
        await self.start();self.assertEqual(len(self.requests),2)
    async def test_retry_after_uses_bounded_same_model_and_no_tools_for_question(self):
        self.mode='rate';started=time.monotonic();await self.start(prompt='Python 的装饰器是什么？')
        self.assertGreaterEqual(time.monotonic()-started,.9);self.assertEqual(self.requests,['a-model','a-model'])
        self.assertFalse(any(e['type']=='tool.completed' for e in self.ws.messages))
