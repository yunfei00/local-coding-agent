"""Real HTTP provider + Task tools; only model decisions are mocked, no paid API."""
import asyncio
from contextlib import nullcontext
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from aiohttp import web
from agent.core.budget import request_token_reservation
from agent.core.context import ContextBudgetManager
from agent.core.verification import VerificationEngine
from agent.tools.base import ToolError
from agent.llm.base import ProviderError
from agent.llm.router import validate_config
from agent.server.main import AgentServer
from test_m2_projects import Client

ROOT = Path(__file__).resolve().parents[1]


class ApiContextFitTests(unittest.TestCase):
    def test_prior_tool_exchange_is_atomic_after_a_new_user_message(self):
        messages=[{'role':'system','content':'permissions'}, {'role':'user','content':'old goal'},
            {'role':'assistant','content':'','tool_calls':[{'id':'prior','type':'function',
             'function':{'name':'read_file','arguments':{'path':'x'*1500}}}]},
            {'role':'tool','tool_call_id':'prior','content':'x'*2500},
            {'role':'user','content':'new goal'}]
        fitted=ContextBudgetManager(context_window_tokens=4096).fit_request(messages,
            tools=[],output_limit=1024,history_messages_total=4)
        headers={c['id'] for m in fitted.messages for c in m.get('tool_calls',[])}
        results={m['tool_call_id'] for m in fitted.messages if m['role']=='tool'}
        self.assertEqual(headers,results,'Never send an orphan tool result after history compaction')
        self.assertEqual(fitted.messages[-1],messages[-1])

    def test_recent_source_stays_complete_when_old_exchanges_can_be_dropped(self):
        manager = ContextBudgetManager(context_window_tokens=16384)
        schema = [{'type':'function','function':{'name':'read_file','description':'schema '*500}}]
        messages = [{'role':'system','content':'KEEP PERMISSIONS'}, {'role':'user','content':'KEEP GOAL'}]
        latest = 'SOURCE START\n' + ('const value = "完整 source";\n'*180) + 'SOURCE END'
        for i in range(6):
            messages.extend([{'role':'assistant','content':'','tool_calls':[{'id':str(i),'type':'function',
                'function':{'name':'read_file','arguments':{'path':f'{i}.tsx'}}}]},
                {'role':'tool','tool_call_id':str(i),'content':latest if i==5 else 'old irrelevant result '*400}])
        fitted = manager.fit_request(messages,tools=schema,output_limit=1024,history_messages_total=0)
        self.assertEqual(fitted.messages[-1]['content'],latest)
        self.assertEqual(fitted.messages[:2],messages[:2])
        self.assertGreater(fitted.usage.runtime_messages_omitted,0)
        self.assertEqual(fitted.usage.truncated_messages,0)
        headers = {c['id'] for m in fitted.messages for c in m.get('tool_calls',[])}
        self.assertEqual(headers,{m['tool_call_id'] for m in fitted.messages if m['role']=='tool'})
        self.assertLessEqual(request_token_reservation(fitted.messages,schema,1024)[1],16384)

    def test_multibyte_large_tool_exchange_fits_with_schema_and_no_orphan_results(self):
        manager = ContextBudgetManager(context_window_tokens=32768)
        schema = [{'type':'function','function':{'name':'read_file','description':'bounded '*900}}]
        messages = [{'role':'system','content':'KEEP PERMISSIONS AND TASK CONTRACT'},
                    {'role':'user','content':'KEEP CURRENT USER GOAL'}]
        calls = [{'id':f'c{i}','type':'function','function':{'name':'read_file','arguments':{'path':f'{i}.txt'}}} for i in range(4)]
        messages.append({'role':'assistant','content':'','tool_calls':calls})
        messages.extend({'role':'tool','tool_call_id':f'c{i}','content':('宽😀"\\\n'*5000)} for i in range(4))
        self.assertGreater(request_token_reservation(messages,schema,1024)[1],32768)
        fitted = manager.fit_request(messages,tools=schema,output_limit=1024,history_messages_total=0)
        self.assertLessEqual(request_token_reservation(fitted.messages,schema,1024)[1],32768)
        self.assertEqual(fitted.messages[:2],messages[:2])
        self.assertEqual({m['tool_call_id'] for m in fitted.messages if m['role']=='tool'}, {c['id'] for c in calls})
        self.assertEqual(fitted.messages[2]['tool_calls'],calls)
        self.assertEqual(fitted.usage.estimation_method,'utf8_bytes_conservative')

    def test_fixed_schema_too_large_has_numeric_failure_without_changing_limits(self):
        manager = ContextBudgetManager(context_window_tokens=4096)
        schema = [{'type':'function','function':{'name':'read_file','description':'x'*5000}}]
        with self.assertRaises(ProviderError) as caught:
            manager.fit_request([{'role':'system','content':'KEEP'},{'role':'user','content':'GOAL'}],
                                tools=schema,output_limit=1024,history_messages_total=0)
        self.assertEqual(caught.exception.code,'MODEL_CONTEXT_LIMIT')
        self.assertFalse(caught.exception.context_details['request_sent'])
        self.assertEqual(manager.context_window_tokens,4096)


class ApiContextTaskTests(unittest.IsolatedAsyncioTestCase):
    async def test_large_reads_then_real_patch_unittest_diff_through_http_task(self):
        await self.scenario(4)

    async def test_mid_execution_budget_failure_keeps_field_values_and_role(self):
        await self.scenario(1)

    async def test_verifier_cleanup_failure_pauses_with_original_error_not_internal_error(self):
        await self.scenario(4,cleanup_fault=True)

    async def scenario(self,max_calls,cleanup_fault=False):
        with tempfile.TemporaryDirectory(prefix='api-context-') as temporary:
            root = Path(temporary)
            with patch.dict(os.environ,{'LCA_DATA_DIR':str(root/'data'),'LCA_OPENAI_API_KEY':''}):
                source = root/'source'
                shutil.copytree(ROOT/'manual-fixtures/v04-local-first',source)
                for name in ('large-a.txt','large-b.txt'):
                    (source/name).write_text('宽😀"\\\n'*6000,encoding='utf-8')
                for args in (['init','-q','-b','main'],['config','user.name','Context fixture'],
                             ['config','user.email','fixture@example.test'],['add','.'],['commit','-qm','fixture']):
                    subprocess.run(['git',*args],cwd=source,check=True,capture_output=True)
                server = AgentServer('test-only')
                client = Client(server)
                project,thread,_ = server.projects.open(source,active_model='profile:coder')
                requests = []
                def call(name,arguments,id):
                    return {'id':id,'type':'function','function':{'name':name,'arguments':json.dumps(arguments)}}
                command = 'uv run --no-project python -m unittest discover -s tests -v'
                choices = [
                    [call('read_file',{'path':p},f'read{i}') for i,p in enumerate(('calculator.py','large-a.txt','large-b.txt'))],
                    [call('apply_patch',{'path':'calculator.py','old_text':'return a - b','new_text':'return a + b'},'patch')],
                    [call('run_command',{'command':command},'test'),call('git_diff',{},'diff')], []]
                async def chat(request):
                    body = await request.json();requests.append(body)
                    self.assertLessEqual(len(requests),4)
                    if len(requests)==2:
                        self.assertIn('[Context truncated]',str(body['messages']))
                        headers = {c['id'] for m in body['messages'] for c in m.get('tool_calls',[])}
                        self.assertTrue(all(m['tool_call_id'] in headers for m in body['messages'] if m['role']=='tool'))
                    calls = choices[len(requests)-1]
                    return web.json_response({'choices':[{'message':{'content':'' if calls else 'Verified real tests and Diff',
                        **({'tool_calls':calls} if calls else {})},'finish_reason':'tool_calls' if calls else 'stop'}],
                        'usage':{'prompt_tokens':20,'completion_tokens':5}})
                app = web.Application();app.router.add_post('/v1/chat/completions',chat)
                http = web.AppRunner(app);await http.setup()
                site = web.TCPSite(http,'127.0.0.1',0);await site.start()
                port = site._server.sockets[0].getsockname()[1]
                config = validate_config({'strategy':'single-agent','roles':{'executor':{'model_profile_id':'coder'}},
                    'budget':{'api_calls':max_calls,'api_tokens':60000,'global_api_calls':4,'global_api_tokens':60000},
                    'verification_commands':[command,'git diff --check']})
                catalog = {'connections':[{'connection_id':'http','display_name':'HTTP Mock only','enabled':True,
                    'provider_type':'openai_compatible','base_url':f'http://127.0.0.1:{port}/v1','credential_reference':None}],
                    'profiles':[{'model_profile_id':'coder','connection_id':'http','display_name':'Mock coder','model_id':'mock-coder',
                                 'context_window':32768,'max_output_tokens':1024}]}
                try:
                    await server.tasks.handle(client,{'type':'task.catalog.update','payload':{'catalog':catalog,'config':config}},set())
                    async def cleanup_failed(_engine,_commands):
                        raise ToolError('PROCESS_CLEANUP_FAILED','Owned verifier process exit could not be confirmed')
                    # Explicit infrastructure fault injection, never counted as
                    # a successful native process/GUI acceptance.
                    with patch.object(VerificationEngine,'run',cleanup_failed) if cleanup_fault else nullcontext():
                        await server.tasks.handle(client,{'type':'task.start','thread_id':thread.id,
                            'payload':{'goal':'Read calculator and large-a.txt and large-b.txt, repair addition, run unittest and inspect Diff.', 'config':config}},set())
                        await asyncio.wait_for(asyncio.gather(*list(server.active_turns.values())),120)
                    task = server.tasks.runtime.list(thread.id)[0]
                    if cleanup_fault:
                        self.assertEqual(task['status'],'paused',task['reason'])
                        self.assertEqual(task['last_error']['code'],'PROCESS_CLEANUP_FAILED')
                        self.assertEqual(task['last_error']['phase'],'verifying')
                        self.assertFalse(task['report'].get('passed'))
                        self.assertIn('exit could not be confirmed',task['reason'])
                        self.assertEqual(len(requests),4,'No paid-model repair for an infrastructure cleanup failure')
                        return
                    if max_calls==1:
                        self.assertEqual(task['status'],'paused',task['reason'])
                        self.assertEqual(len(requests),1)
                        error = task['last_error']
                        self.assertEqual(error['role'],'executor')
                        self.assertEqual(error['budget']['field'],'api_calls')
                        self.assertEqual((error['budget']['limit'],error['budget']['used'],error['budget']['required']),(1,1,1))
                        self.assertFalse(error['budget']['request_sent'])
                        return
                    self.assertEqual(task['status'],'awaiting_approval',task['reason'])
                    self.assertEqual(len(requests),4)
                    self.assertTrue(all(v['ok'] for v in task['verification']))
                    self.assertIn('return a + b',(Path(task['workspace'])/'calculator.py').read_text())
                    self.assertIn('return a - b',(source/'calculator.py').read_text())
                    self.assertIn('+    return a + b',task['report']['diff'])
                    self.assertTrue(all(c['usage']['initial_reserved_tokens']<=32768 for c in server.tasks.runtime.calls(task['id'])))
                    self.assertEqual(server.tasks.runtime.usage(task['id'])['api_calls'],4)
                finally:
                    await server.close_async();server.close();await http.cleanup()


if __name__ == '__main__':
    unittest.main()
