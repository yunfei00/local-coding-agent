import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from agent.core.task_diagnostics import export_diagnostics
from agent.llm.router import validate_config
import os
from unittest.mock import patch
from aiohttp import web, ClientSession
from agent.server.main import AgentServer


class DiagnosticTransportTests(unittest.TestCase):
    def test_locked_uv_and_plain_diff_checks_are_repeatable_but_compounds_are_not(self):
        from agent.task_plans import repeatable_check
        for command in ['uv run --locked python -m unittest discover -s tests -v',
                        'uv run pytest', 'uv run --no-project --locked python -m pytest', 'git diff --check']:
            self.assertTrue(repeatable_check('run_command',{'command':command}),command)
        for command in ['uv run pytest; echo changed','git diff --output=secret.txt','uv run python edit.py']:
            self.assertFalse(repeatable_check('run_command',{'command':command}),command)
    def test_large_history_kept_on_disk_but_bounded_on_wire(self):
        calls = [dict(id=str(i),role='executor',route='api',model='model',status='failed',
                      reserved_tokens=100,reserved_cost=0,usage={'error_code':'NETWORK_ERROR'}) for i in range(2000)]
        task = dict(status='paused',planned=True,config=validate_config({}),last_error={
            'code':'VERIFICATION_TIMEOUT','command':'uv run pytest','exit_code':124,'summary':'secret-value'},
            transitions=[{'status':'paused','reason':'timeout'}]*2000,
            verification=[{'command':'GUI acceptance','ok':False,'exit_code':1,'category':'assertion','summary':'Failed GUI wait',
                'evidence':[{'tool':'desktop_wait','ok':False,'error_code':'DESKTOP_WAIT_TIMEOUT',
                    'assertion':{'selector':{'name':'Status: secret-value'},'state':'visible'}}]}])
        plans = SimpleNamespace(executions=lambda _: [{'tool':'run_command','status':'failed'}]*2000,
                                get=lambda _: {'steps':[{'state':'blocked','description':'Run tests'}]})
        runtime = SimpleNamespace(get=lambda _:task,calls=lambda *a,**k:calls,usage=lambda *a:{'api_calls':2000},plans=plans)
        with tempfile.TemporaryDirectory() as directory:
            for _ in range(3):
                result = export_diagnostics(runtime,'task',Path(directory),('secret-value',))
                self.assertIsInstance(result,dict)
                wire = result['diagnostics']
                self.assertEqual(len(wire['json']['calls']),8)
                self.assertEqual(len(wire['json']['transitions']),8)
                self.assertLess(len(json.dumps(wire)),20000)
                self.assertLess(len(wire['markdown'].splitlines()),100)
                self.assertNotIn('secret-value',json.dumps(result))
                self.assertIn('uv run pytest',wire['markdown'])
                self.assertIn('DESKTOP_WAIT_TIMEOUT',wire['markdown'])
                self.assertEqual(wire['json']['verification_failures'][0]['gui_failures'][0]['state'],'visible')
                full = json.loads(Path(result['paths']['json']).read_text(encoding='utf-8'))
                self.assertEqual(len(full['calls']),2000)
                self.assertEqual(full['last_error']['exit_code'],124)
            task['last_error'] = {'code':'MODEL_CONTEXT_LIMIT', 'context':{
                'context_window':50000,'request_reservation':58416,'output_limit':4096,'request_sent':False}}
            diagnostic = export_diagnostics(runtime,'task',Path(directory))['diagnostics']['json']
            self.assertEqual(diagnostic['last_error']['context']['request_reservation'],58416)
            self.assertEqual(diagnostic['budget_explanation']['error_context_details']['context_window'],50000)
            self.assertIsNone(diagnostic['budget_explanation']['error_budget_details'])


class WebSocketRecoveryTests(unittest.IsolatedAsyncioTestCase):
    async def test_real_socket_reconnect_loads_persistent_task_without_starting_it(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {'LCA_DATA_DIR': directory}):
            server = AgentServer('test-secret')
            workspace = Path(directory)/'workspace'; workspace.mkdir()
            project, thread, _ = server.projects.open(workspace, active_model='fixture')
            task = server.tasks.runtime.create(thread.id,'Pending recovery fixture',validate_config({}),str(workspace))
            app = web.Application(); app.router.add_get('/ws',server.websocket)
            runner = web.AppRunner(app); await runner.setup()
            site = web.TCPSite(runner,'127.0.0.1',0); await site.start()
            port = site._server.sockets[0].getsockname()[1]
            try:
                async with ClientSession() as client:
                    for _ in range(2):
                        async with client.ws_connect(f'http://127.0.0.1:{port}/ws',headers={'Authorization':'Bearer test-secret'}) as ws:
                            await ws.send_json({'type':'task.list','request_id':'sync','thread_id':thread.id,'payload':{}})
                            for _ in range(20):
                                message = await ws.receive_json(timeout=10)
                                if message.get('request_id') == 'sync': break
                            self.assertEqual(message['type'],'task.loaded',message)
                            restored = message['payload']['tasks'][0]
                            self.assertEqual((restored['id'],restored['status']),(task['id'],'pending'))
                            self.assertEqual(restored['usage']['api_calls'],0)
            finally:
                await runner.cleanup(); await server.close_async(); server.close()
