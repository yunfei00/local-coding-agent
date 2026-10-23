"""Real HTTP routing and JPEG transport; generated image is NOT a desktop capture."""
import asyncio
import base64
from copy import deepcopy
import json
import unittest
from aiohttp import web
from agent.llm.router import validate_config
from agent.core.model_diagnostics import synthetic_image
import test_v04_orchestration as fixture


class UnifiedChatTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = fixture.TaskTests.asyncSetUp
    asyncTearDown = fixture.TaskTests.asyncTearDown

    async def setup_models(self):
        self.requests = []
        connections, profiles = [], []
        for cid in ('deepseek','qwen'):
            async def chat(request, cid=cid):
                body = await request.json()
                self.requests.append((cid,request.headers.get('Authorization'),body))
                return web.json_response({'choices':[{'message':{'content':'Observed fixture' if not body.get('tools') else 'Completed response'},'finish_reason':'stop'}], 'usage':{'prompt_tokens':20,'completion_tokens':5}})
            app = web.Application(); app.router.add_post('/v1/chat/completions',chat)
            runner = web.AppRunner(app); await runner.setup(); self.addAsyncCleanup(runner.cleanup)
            site=web.TCPSite(runner,'127.0.0.1',0); await site.start()
            connections.append({'connection_id':cid,'display_name':cid,'provider_type':'openai_compatible',
                'base_url':f'http://127.0.0.1:{site._server.sockets[0].getsockname()[1]}/v1','credential_reference':'connection-'+cid,'enabled':True})
            profiles.append({'model_profile_id':cid+'-same','connection_id':cid,'model_id':'same-model',
                'display_name':'Same ID', 'supports_vision':cid=='qwen','max_output_tokens':256})
        self.catalog={'connections':connections,'profiles':profiles}
        self.config=validate_config({'strategy':'single-agent','roles':{'executor':{'model_profile_id':'qwen-same'}}})
        self.server.tasks.credentials={'connection-deepseek':'mock-deepseek-only','connection-qwen':'mock-qwen-only'}
        await self.save()

    async def save(self, **extra):
        await self.server.tasks.handle(self.ws,{'type':'task.catalog.update','payload':{'catalog':self.catalog,'config':self.config,**extra}},set())
        self.assertEqual(self.ws.messages[-1]['type'],'task.loaded',self.ws.messages[-1])

    async def chat(self, selection):
        await self.server.handle_message(self.ws,{'type':'turn.start','thread_id':self.thread.id,'payload':{'prompt':'Respond briefly','model':selection}},set())
        await asyncio.wait_for(asyncio.gather(*list(self.server.active_turns.values())),10)

    async def test_same_model_different_connections_and_task_executor_independent(self):
        await self.setup_models()
        for pid,cid,key in (('deepseek-same','deepseek','mock-deepseek-only'),('qwen-same','qwen','mock-qwen-only')):
            await self.chat('profile:'+pid)
            actual=self.requests[-1]
            self.assertEqual(actual[:2],(cid,'Bearer '+key))
            self.assertEqual(actual[2]['model'],'same-model')
            self.assertEqual(self.server.projects.active.state.get_thread(self.thread.id).active_model,'profile:'+pid)
        self.assertEqual(self.server.tasks.settings()['roles']['executor']['model_profile_id'],'qwen-same')
        self.assertTrue(self.server.chat_provider('profile:qwen-same')[0].supports_vision)
        self.assertFalse(self.server.chat_provider('profile:deepseek-same')[0].supports_vision)

    async def test_missing_disabled_profile_never_silently_falls_back(self):
        await self.setup_models()
        for selection in ('profile:missing','profile:deepseek-same'):
            self.catalog['connections'][0]['enabled']=False
            await self.save()
            await self.chat(selection)
            self.assertEqual(self.ws.messages[-1]['type'],'error')
            self.assertEqual(self.ws.messages[-1]['payload']['code'],'CHAT_PROFILE_UNAVAILABLE')
        self.assertEqual(self.requests,[])

    async def test_observer_gets_jpeg_coder_gets_observation_and_no_repeated_image(self):
        await self.setup_models(); await self.save(chat_vision='qwen-same')
        image,_=synthetic_image()
        original=self.ws.send_json
        async def send(event):
            await original(event)
            if event['type']=='turn.started':
                owner=event['turn_id']
                self.project.tools.desktop.images[owner]={'type':'image_url','image_url':{'url':image}}
        self.ws.send_json=send
        await self.chat('profile:deepseek-same')
        self.assertEqual([r[0] for r in self.requests],['qwen','deepseek'])
        vision=self.requests[0][2]
        self.assertFalse(vision.get('tools'))
        raw=vision['messages'][1]['content'][1]['image_url']['url']
        self.assertTrue(base64.b64decode(raw.split(',')[1]).startswith(b'\xff\xd8'))
        coder=json.dumps(self.requests[1][2])
        self.assertNotIn('base64',coder)
        self.assertIn('Untrusted screenshot observation',coder)
        self.assertFalse(self.project.tools.desktop.images)
        event=next(e for e in self.ws.messages if e['type']=='vision.observed')
        self.assertEqual(event['payload']['vision_profile_id'],'qwen-same')

    async def test_vision_chat_direct_attachment_is_consumed_once(self):
        await self.setup_models()
        image,_=synthetic_image()
        original=self.ws.send_json
        async def send(event):
            await original(event)
            if event['type']=='turn.started': self.project.tools.desktop.images[event['turn_id']]={'type':'image_url','image_url':{'url':image}}
        self.ws.send_json=send
        await self.chat('profile:qwen-same')
        self.assertEqual(len(self.requests),1)
        self.assertIn('data:image/jpeg;base64,',json.dumps(self.requests[0][2]))
        self.assertFalse(self.project.tools.desktop.images)

    async def test_defaults_atomic_invalid_save_preserves_catalog_and_credentials(self):
        await self.setup_models(); await self.save(chat_default='qwen-same')
        before=self.server.store.get_setting('models.catalog.v1')
        await self.server.tasks.handle(self.ws,{'type':'task.catalog.update','payload':{'catalog':self.catalog,'config':self.config,'chat_vision':'deepseek-same'}},set())
        self.assertEqual(self.ws.messages[-1]['type'],'error')
        self.assertEqual(self.server.store.get_setting('models.catalog.v1'),before)
        self.assertEqual(self.server.store.get_setting('chat.default_profile_id'),'qwen-same')
        self.assertEqual(len(self.server.tasks.credentials),2)

    async def test_old_chat_no_longer_guesses_executor_by_model_name(self):
        await self.setup_models()
        legacy=self.server.provider
        self.server.available_models={'same-model'}
        # Explicit profile path differs from legacy even when model IDs match.
        selected,model=self.server.chat_provider('profile:deepseek-same')
        self.assertIsNot(selected,legacy)
        self.assertEqual(selected.chat_identity['connection_id'],'deepseek')
        self.assertEqual(model,'same-model')

    async def test_missing_connection_key_blocks_before_http(self):
        await self.setup_models()
        self.server.tasks.credentials.pop('connection-deepseek')
        await self.chat('profile:deepseek-same')
        self.assertEqual(self.requests,[])
        self.assertIn('API_KEY_MISSING',self.ws.messages[-1]['payload']['message'])

    async def test_profile_default_and_threads_survive_store_reload(self):
        await self.setup_models(); await self.save(chat_default='qwen-same')
        await self.chat('profile:deepseek-same')
        self.project.state.load_from_store()
        self.assertEqual(self.project.state.get_thread(self.thread.id).active_model,'profile:deepseek-same')
        self.assertEqual(self.server.store.get_setting('chat.default_profile_id'),'qwen-same')
        await self.server.handle_message(self.ws,{'type':'thread.create','payload':{}},set())
        self.assertEqual(self.ws.messages[-1]['payload']['thread']['active_model'],'profile:qwen-same')

    async def test_task_observer_binding_without_gui_is_frozen_and_explicitly_clearable(self):
        await self.setup_models()
        config=validate_config({**self.config,'vision_profile_id':'qwen-same'})
        self.assertEqual(self.server.tasks.vision_binding(config)['model_profile_id'],'qwen-same')
        from agent.llm.router import apply_config_overrides
        changed=apply_config_overrides(config,{'vision_profile_id':None})
        self.assertIsNone(self.server.tasks.vision_binding(changed))
        with self.assertRaises(ValueError):
            self.server.tasks.vision_binding(validate_config({**config,'strategy':'local-only'}))

    async def test_task_observer_actual_http_is_charged_to_original_task_budget(self):
        await self.setup_models()
        image,_=synthetic_image()  # Protocol fixture, never claimed as Windows capture.
        original=self.server.run_tool_turn
        async def capture_then_run(ws,**kwargs):
            kwargs['project_override'].tools.desktop.images[kwargs['turn_id']]={'type':'image_url','image_url':{'url':image}}
            await original(ws,**kwargs)
        self.server.run_tool_turn=capture_then_run
        config=validate_config({**self.config,'roles':{'executor':{'model_profile_id':'deepseek-same'}},
            'vision_profile_id':'qwen-same','budget':{'api_calls':2,'api_tokens':30000},
            'verification_commands':['uv run --no-project python -m unittest discover -s tests -v']})
        await self.server.tasks.handle(self.ws,{'type':'task.start','thread_id':self.thread.id,'payload':{'goal':'Fix calculator','config':config}},set())
        await asyncio.wait_for(asyncio.gather(*list(self.server.active_turns.values())),30)
        task=self.server.tasks.runtime.list(self.thread.id)[0]
        self.assertEqual([r[0] for r in self.requests],['qwen','deepseek'])
        self.assertEqual(task['status'],'paused')
        calls=self.server.tasks.runtime.calls(task['id'])
        self.assertEqual([c['role'] for c in calls],['vision-observer','executor'])
        self.assertEqual(self.server.tasks.runtime.usage(task['id'])['api_calls'],2)
        self.assertNotEqual(task['status'],'completed')

    async def test_saved_vision_test_becomes_stale_when_profile_changes(self):
        await self.setup_models()
        self.server.store.set_setting('model.test.qwen-same',json.dumps({'vision':'PASS','config_fingerprint':self.server.tasks.catalog().fingerprint('qwen-same')}))
        self.assertEqual(self.server.tasks.catalog().test_result('qwen-same')['vision'],'PASS')
        self.catalog['profiles'][1]['supports_vision']=False
        await self.save()
        self.assertEqual(self.server.tasks.catalog().test_result('qwen-same')['vision'],'STALE')
