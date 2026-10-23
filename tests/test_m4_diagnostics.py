import asyncio
import base64
import json
from io import BytesIO
import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch

from agent.core.model_diagnostics import ModelDiagnostics
from agent.llm.base import ProviderChunk, ProviderError, ToolCall
from agent.llm.openai_compatible import OpenAICompatibleProvider
from agent.server.main import AgentServer
from test_m2_projects import Client

CONNECTION = {'connection_id':'bailian', 'display_name':'Bailian', 'provider_type':'openai_compatible', 'base_url':'https://example.test/v1', 'credential_reference':'connection-bailian', 'enabled':True}
PROFILE = {'model_profile_id':'vision', 'connection_id':'bailian', 'model_id':'configured-model', 'display_name':'Configured', 'context_window':32768, 'temperature':None, 'supports_vision':False}


class DecisionModel:
    api_key = 'fixture-secret-not-real'
    def __init__(self, mode='valid'):
        self.mode, self.requests = mode, []
        self.started = asyncio.Event()
    async def stream_chat(self, **request):
        self.requests.append(request)
        if self.mode == 'block':
            self.started.set()
            await asyncio.Event().wait()
        if self.mode in ('auth', 'model', 'timeout'):
            raise ProviderError({'auth':'OPENAI_COMPATIBLE_AUTH_FAILED', 'model':'OPENAI_COMPATIBLE_HTTP_404', 'timeout':'MODEL_TIMEOUT'}[self.mode], self.api_key)
        if request['tools']:
            yield ProviderChunk(done=True, tool_calls=() if self.mode == 'no-tools' else (ToolCall('lca_diagnostic_echo', {'value':'LCA_OK'}),), prompt_eval_count=9, eval_count=4)
        elif isinstance(request['messages'][0]['content'], list):
            content=request['messages'][0]['content']
            raw=base64.b64decode(content[1]['image_url']['url'].split(',')[1])
            from PIL import Image
            with Image.open(BytesIO(raw)) as image:
                assert image.format == 'JPEG' and image.size == (640,360)
            assert 'A1B2C3' not in content[0]['text']
            value={'title':'LCA Vision Test', 'button_color':'blue', 'button_text':'Settings', 'input_boxes':1, 'check_text':'CHECK-A1B2C3' if self.mode != 'no-vision' else 'CHECK-WRONG'}
            yield ProviderChunk(content=json.dumps(value), done=True, prompt_eval_count=20, eval_count=30)
        else:
            yield ProviderChunk(content='LCA_OK', done=True, prompt_eval_count=5, eval_count=3)


class DiagnosticsTests(unittest.IsolatedAsyncioTestCase):
    def test_cli_missing_key_is_read_only_and_returns_failure_without_requests(self):
        import hashlib
        import os
        import sqlite3
        import subprocess
        import sys
        from contextlib import closing
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'local-coding-agent.sqlite3'
            with closing(sqlite3.connect(path)) as db:
                db.execute('CREATE TABLE settings (key TEXT PRIMARY KEY,value TEXT NOT NULL)')
                db.execute('INSERT INTO settings VALUES (?,?)',('models.catalog.v1',json.dumps({'connections':[CONNECTION],'profiles':[PROFILE]})))
                db.commit()
            before=hashlib.sha256(path.read_bytes()).hexdigest()
            script=Path(__file__).resolve().parents[1]/'scripts/validation/model_diagnostics.py'
            result=subprocess.run([sys.executable,str(script),'--data-dir',directory,'--profile','vision'],capture_output=True,text=True,encoding='utf-8',env={**os.environ,'LCA_DIAGNOSTIC_API_KEY':''},timeout=15)
            self.assertEqual(result.returncode,2,result.stderr)
            report=json.loads(result.stdout)
            self.assertEqual(report['configuration'],'FAIL')
            self.assertEqual(report['requests'],0)
            self.assertEqual(report['vision'],'NOT RUN')
            self.assertEqual(before,hashlib.sha256(path.read_bytes()).hexdigest())

    async def test_real_websocket_diagnostics_do_not_block_chat_requests_or_stop(self):
        from aiohttp import web, ClientSession
        from aiohttp.test_utils import TestServer
        from agent.llm.router import validate_config
        with tempfile.TemporaryDirectory() as directory, patch.dict('os.environ',{'LCA_DATA_DIR':directory,'LCA_OPENAI_API_KEY':''}):
            server=AgentServer('fixture'); client=Client(server); provider=DecisionModel('block')
            server.tasks.provider_factory_override=lambda *_:provider
            await server.tasks.handle(client,{'type':'task.catalog.update','payload':{'catalog':{'connections':[CONNECTION],'profiles':[PROFILE]},'config':validate_config()}},set())
            app=web.Application();app.router.add_get('/ws',server.websocket)
            host=TestServer(app)
            await host.start_server()
            try:
                async with ClientSession() as session:
                    async with session.ws_connect(host.make_url('/ws'),headers={'Authorization':'Bearer fixture'}) as ws:
                        await ws.receive_json()
                        await ws.send_json({'type':'task.model.diagnostic','request_id':'probe','payload':{'connection_id':'bailian','model_profile_id':'vision','live':True}})
                        await asyncio.wait_for(provider.started.wait(),2)
                        await ws.send_json({'type':'task.catalog.get','request_id':'input','payload':{}})
                        result=await asyncio.wait_for(ws.receive_json(),2)
                        self.assertEqual(result['request_id'],'input')
                        await ws.send_json({'type':'task.model.diagnostic.cancel','request_id':'stop','payload':{'connection_id':'bailian'}})
                        replies=[await asyncio.wait_for(ws.receive_json(),2) for _ in range(2)]
                        probe=next(r for r in replies if r['request_id']=='probe')
                        self.assertEqual(probe['payload']['text'],'FAIL')
                        self.assertEqual(probe['payload']['tools'],'NOT RUN')
                        self.assertEqual(len(provider.requests),1)
            finally:
                await host.close();await server.close_async();server.close()

    async def test_real_http_provider_transmits_jpeg_and_native_schema_without_retry(self):
        from aiohttp import web
        from aiohttp.test_utils import TestServer
        requests=[]
        async def respond(request):
            payload=await request.json();requests.append(payload)
            self.assertEqual(request.headers['Authorization'],'Bearer fixture-key')
            self.assertEqual(payload['max_tokens'],256)
            message={'content':'LCA_OK'}
            if isinstance(payload['messages'][0]['content'],list):
                image=payload['messages'][0]['content'][1]['image_url']['url']
                self.assertTrue(base64.b64decode(image.split(',')[1]).startswith(b'\xff\xd8'))
                message['content']=json.dumps({'title':'LCA Vision Test','button_color':'blue','button_text':'Settings','input_boxes':1,'check_text':'CHECK-A1B2C3'})
            if payload.get('tools'):
                message={'content':None,'tool_calls':[{'id':'test','type':'function','function':{'name':'lca_diagnostic_echo','arguments':'{"value":"LCA_OK"}'}}]}
            return web.json_response({'choices':[{'message':message,'finish_reason':'tool_calls' if payload.get('tools') else 'stop'}],'usage':{'prompt_tokens':11,'completion_tokens':7}})
        app=web.Application();app.router.add_post('/v1/chat/completions',respond)
        async with TestServer(app) as host:
            url=str(host.make_url('/v1'))
            provider=OpenAICompatibleProvider(base_url=url,api_key='fixture-key')
            with patch('agent.core.model_diagnostics.secrets.token_hex',return_value='a1b2c3'):
                result=await ModelDiagnostics().run(provider,{**CONNECTION,'base_url':url},PROFILE,live=True)
        self.assertEqual(result['vision'],'PASS')
        self.assertEqual(result['tools'],'PASS')
        self.assertEqual(len(requests),3)
        self.assertTrue(all(u['http_status']==200 for u in result['usage']))

    async def test_http_auth_and_model_errors_do_not_echo_gateway_secrets(self):
        from aiohttp import web
        from aiohttp.test_utils import TestServer
        for status in (401,404):
            count=[]
            async def reject(request):
                count.append(await request.json())
                return web.json_response({'error':{'message':'echoed-fixture-secret'}},status=status)
            app=web.Application();app.router.add_post('/v1/chat/completions',reject)
            async with TestServer(app) as host:
                url=str(host.make_url('/v1'))
                report=await ModelDiagnostics().run(OpenAICompatibleProvider(base_url=url,api_key='echoed-fixture-secret'),{**CONNECTION,'base_url':url},PROFILE,live=True)
            self.assertEqual(len(count),1)
            self.assertEqual(report['text'],'FAIL')
            self.assertEqual(report['vision'],'NOT RUN')
            self.assertEqual(report['usage'][0]['http_status'],status)
            self.assertNotIn('echoed-fixture-secret',json.dumps(report))

    def test_catalog_rejects_cross_connection_key_reference_and_invalid_port(self):
        from agent.core.model_catalog import validate_catalog
        for connection in ({**CONNECTION,'credential_reference':'legacy-openai'}, {**CONNECTION,'base_url':'https://example.test:invalid/v1'}):
            with self.assertRaises(ValueError):
                validate_catalog({'connections':[connection],'profiles':[PROFILE]})

    async def run_probe(self, mode='valid', **options):
        provider=DecisionModel(mode)
        with patch('agent.core.model_diagnostics.secrets.token_hex',return_value='a1b2c3'):
            report=await ModelDiagnostics().run(provider,CONNECTION,PROFILE,**options)
        self.assertNotIn(provider.api_key,json.dumps(report))
        return provider,report

    async def test_offline_never_requests_or_claims_network_success(self):
        provider,report=await self.run_probe()
        self.assertEqual(provider.requests,[])
        self.assertEqual(report['configuration'],'PASS')
        self.assertTrue(all(report[k]=='NOT RUN' for k in ('connection','text','vision','tools')))

    async def test_three_requests_actual_jpeg_assertions_usage_and_no_tool_execution(self):
        provider,report=await self.run_probe(live=True)
        self.assertEqual(report['requests'],3)
        self.assertEqual(len(provider.requests),3)
        self.assertTrue(all(report[k]=='PASS' for k in ('connection','text','vision','tools')))
        self.assertFalse(report['declared_supports_vision'])
        self.assertEqual(provider.request_timeout,60)
        self.assertEqual(provider.max_output_tokens,256)
        self.assertEqual(sum(v['input_tokens'] for v in report['usage']),34)
        self.assertIsNone(report['cost'])

    async def test_http_success_without_image_recognition_fails(self):
        _,report=await self.run_probe('no-vision',live=True)
        self.assertEqual(report['vision'],'FAIL')
        self.assertEqual(report['text'],'PASS')

    async def test_no_native_function_calling_fails(self):
        _,report=await self.run_probe('no-tools',live=True)
        self.assertEqual(report['tools'],'FAIL')

    async def test_auth_model_timeout_do_not_retry_or_spend_remaining_requests(self):
        for mode in ('auth','model','timeout'):
            with self.subTest(mode=mode):
                provider,report=await self.run_probe(mode,live=True)
                self.assertEqual(len(provider.requests),1)
                self.assertEqual(report['text'],'FAIL')
                self.assertEqual(report['vision'],'NOT RUN')
                self.assertEqual(report['tools'],'NOT RUN')

    async def test_missing_key_and_wrong_connection_block_live(self):
        for connection,key in (({**CONNECTION,'connection_id':'wrong'},'fixture'),(CONNECTION,'')):
            provider=DecisionModel(); provider.api_key=key
            report=await ModelDiagnostics().run(provider,connection,PROFILE,live=True)
            self.assertEqual(report['configuration'],'FAIL')
            self.assertEqual(provider.requests,[])

    async def test_cancel_and_parallel_click_are_bounded(self):
        service=ModelDiagnostics(); provider=DecisionModel('block')
        pending=asyncio.create_task(service.run(provider,CONNECTION,PROFILE,live=True))
        await provider.started.wait()
        with self.assertRaises(ValueError):
            await service.run(provider,CONNECTION,PROFILE,live=True)
        service.cancel('bailian')
        report=await asyncio.wait_for(pending,2)
        self.assertEqual(report['requests'],1)
        self.assertEqual(report['text'],'FAIL')
        self.assertEqual(report['errors'][-1]['code'],'CANCELLED')
        self.assertFalse(service.running)

    async def test_ui_protocol_profile_binding_and_independent_credentials(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict('os.environ',{'LCA_DATA_DIR':directory,'LCA_OPENAI_API_KEY':''}):
            server=AgentServer('fixture'); client=Client(server)
            try:
                other={**CONNECTION,'connection_id':'other','credential_reference':'connection-other'}
                catalog={'connections':[CONNECTION,other], 'profiles':[PROFILE,{**PROFILE,'model_profile_id':'other-profile','connection_id':'other'}]}
                from agent.llm.router import validate_config
                await server.tasks.handle(client,{'type':'task.catalog.update','payload':{'catalog':catalog,'config':validate_config()}},set())
                server.tasks.credentials={'connection-bailian':'fixture-one','connection-other':'fixture-two'}
                for pid,cid in (('vision','bailian'),('other-profile','other')):
                    await server.tasks.handle(client,{'type':'task.model.diagnostic','payload':{'model_profile_id':pid,'connection_id':cid}},set())
                    self.assertEqual(client.messages[-1]['payload']['configuration'],'PASS',client.messages[-1])
                self.assertEqual(server.tasks.credentials['connection-other'],'fixture-two')
                await server.tasks.handle(client,{'type':'task.model.diagnostic','payload':{'model_profile_id':'vision','connection_id':'other'}},set())
                self.assertEqual(client.messages[-1]['type'],'error')
            finally:
                await server.close_async();server.close()
