"""通过本机真实 HTTP 传输注入故障，检查请求事件和敏感数据边界。"""
import asyncio
import json
import sqlite3
import unittest

from aiohttp import web
from agent.core.runtime_events import RuntimeLedger
from agent.llm.base import ProviderError
from agent.llm.openai_compatible import OpenAICompatibleProvider


class RequestTracingTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.db=sqlite3.connect(':memory:')
        self.ledger=RuntimeLedger(self.db,lambda:('test-private-key',))
        self.mode='normal';self.requests=0
        self.entered=asyncio.Event();self.release=asyncio.Event()
        async def chat(request):
            self.requests+=1
            self.entered.set()
            if self.mode=='timeout':
                await self.release.wait()
            if self.mode=='429':return web.json_response({'error':{'message':'private provider message'}},status=429)
            response=web.StreamResponse(headers={'Content-Type':'text/event-stream'})
            await response.prepare(request)
            if self.mode=='cancel':
                await self.release.wait()
                return response
            payload={'choices':[{'delta':{'content':'private answer'},'finish_reason':'stop'}],
                     'usage':{'prompt_tokens':14,'completion_tokens':3,'total_tokens':17}}
            wire=('data: '+json.dumps(payload)+'\n\n'+'data: [DONE]\n\n').encode()
            for start in range(0,len(wire),7):await response.write(wire[start:start+7])
            await response.write_eof()
            return response
        app=web.Application();app.router.add_post('/v1/chat/completions',chat)
        self.runner=web.AppRunner(app);await self.runner.setup()
        site=web.TCPSite(self.runner,'127.0.0.1',0);await site.start()
        port=site._server.sockets[0].getsockname()[1]
        self.provider=OpenAICompatibleProvider(base_url=f'http://127.0.0.1:{port}/v1',api_key='test-private-key')
        self.provider.request_observer=self.ledger.request_callback('run','thread','call',{'role':'executor','model':'test'})

    async def asyncTearDown(self):
        self.release.set()
        await self.runner.cleanup()
        self.db.close()

    async def consume(self,messages=None):
        return [chunk async for chunk in self.provider.stream_chat(model='test',messages=messages or [{'role':'user','content':'private prompt'}])]

    def events(self):return self.ledger.events(run_id='run')

    async def test_split_stream_has_one_correlated_stage_chain_without_content(self):
        chunks=await self.consume()
        self.assertTrue(chunks[-1].done)
        events=self.events()
        self.assertEqual([e['kind'] for e in events],['request.prepared','request.dispatched','response.headers_received','response.streaming','response.completed'])
        self.assertEqual({e['request_id'] for e in events},{'call'})
        self.assertEqual(events[-1]['metadata']['input_tokens'],14)
        serialized=json.dumps(events)
        for value in ('private prompt','private answer','test-private-key','Authorization'):
            self.assertNotIn(value,serialized)

    async def test_serialization_failure_sends_no_http_and_has_exact_error(self):
        self.provider.temperature=float('nan')
        with self.assertRaises(ProviderError) as caught:await self.consume()
        self.assertEqual(caught.exception.code,'REQUEST_CONSTRUCTION_FAILED')
        self.assertEqual(self.requests,0)
        self.assertEqual([e['kind'] for e in self.events()],['request.prepared','request.failed'])
        self.assertIs(self.events()[-1]['metadata']['request_sent'],False)

    async def test_http_429_is_sent_failure_not_connection_failure(self):
        self.mode='429'
        with self.assertRaises(ProviderError):await self.consume()
        self.assertEqual(self.requests,1)
        last=self.events()[-1]
        self.assertEqual(last['kind'],'request.failed')
        self.assertEqual(last['metadata']['http_status'],429)
        self.assertIs(last['metadata']['request_sent'],True)
        self.assertNotIn('private provider message',json.dumps(self.events()))

    async def test_timeout_before_headers_is_unknown_not_proven_unsent(self):
        self.mode='timeout';self.provider.request_timeout=.5
        try:
            with self.assertRaises(ProviderError) as caught:await self.consume()
            self.assertEqual(caught.exception.code,'MODEL_TIMEOUT')
            self.assertEqual(self.requests,1)
            self.assertIsNone(self.events()[-1]['metadata']['request_sent'])
            self.assertNotIn('response.completed',[e['kind'] for e in self.events()])
        finally:self.release.set()

    async def test_cancel_keeps_interrupted_trace_without_completion(self):
        self.mode='cancel'
        task=asyncio.create_task(self.consume())
        await asyncio.wait_for(self.entered.wait(),2)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):await task
        self.assertEqual(self.events()[-1]['kind'],'request.interrupted')
        self.assertNotIn('response.completed',[e['kind'] for e in self.events()])
