"""Real Electron/React repair and GUI. Only model decisions use local HTTP mocks."""
import asyncio
import base64
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from aiohttp import web

from agent.core.gui_verification import validate_gui
from agent.core.verification import acceptance_changes, acceptance_snapshot
from agent.llm.base import ProviderChunk
from agent.llm.router import validate_config
from agent.server.main import AgentServer
from test_m2_projects import Client, ModelResponses, tool, command, last_result, poll_ready, process_id
from test_m2_processes import alive

ROOT=Path(__file__).resolve().parents[1]
FIXTURE=ROOT/'manual-fixtures/m5-electron-e2e'


class M5ContractTests(unittest.TestCase):
    def test_contract_and_gui_launcher_are_frozen_independently(self):
        gui=validate_gui(json.loads((FIXTURE/'.lca/gui-verification.json').read_text()))
        self.assertEqual(gui['window_title'],'M5 Electron acceptance')
        self.assertEqual(sum(s['tool']=='desktop_type_text' for s in gui['steps']),2)
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            shutil.copytree(FIXTURE,root,dirs_exist_ok=True,ignore=shutil.ignore_patterns('node_modules','dist','.runtime'))
            baseline=acceptance_snapshot(root)
            package=root/'package.json'; value=json.loads(package.read_text());value['scripts']['start']='node fake.cjs';package.write_text(json.dumps(value))
            self.assertIn('package.json',acceptance_changes(root,baseline))
            value=json.loads((FIXTURE/'package.json').read_text());value['scripts']['prestart']='node fake.cjs';package.write_text(json.dumps(value))
            self.assertIn('package.json',acceptance_changes(root,baseline),'New lifecycle hook must not bypass the frozen GUI launcher')
            value=json.loads((FIXTURE/'package.json').read_text());value['scripts']['pretypecheck']='node fake.cjs';package.write_text(json.dumps(value))
            self.assertIn('package.json',acceptance_changes(root,baseline),'Typecheck lifecycle hooks are part of the independent gate')
            package.write_text((FIXTURE/'package.json').read_text())
            old={'package.json':{'scripts':{'test':value['scripts']['test']}}}
            self.assertEqual(acceptance_changes(root,old),[],'Legacy snapshots remain readable')
            (root/'.lca/gui-verification.json').write_text('{}')
            self.assertIn(str(Path('.lca/gui-verification.json')),acceptance_changes(root,baseline))


@unittest.skipUnless(sys.platform=='win32','Real Windows Electron UIA required, never substitute a simulated GUI')
class ElectronE2ETests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        from windows_desktop_support import require_test_desktop
        require_test_desktop()
        self.temp=tempfile.TemporaryDirectory(prefix='m5-e2e-');self.root=Path(self.temp.name)
        self.env=patch.dict(os.environ,{'LCA_DATA_DIR':str(self.root/'data'),'LCA_OPENAI_API_KEY':'',
            'LCA_EXECUTION_TOKENS':'6000000'});self.env.start()
        self.source=self.root/'repo'
        shutil.copytree(FIXTURE,self.source,ignore=shutil.ignore_patterns('node_modules','dist','.runtime'))
        for args in (['init','-q','-b','main'],['config','user.name','M5 fixture'],['config','user.email','m5@example.test'],['add','.'],['commit','-qm','fixture']):
            subprocess.run(['git',*args],cwd=self.source,check=True,capture_output=True)
        self.server=AgentServer('fixture');self.server.permissions.set_mode('full_access')
        self.client=Client(self.server)
        self.project,self.thread,_=self.server.projects.open(self.source,active_model='profile:coder')
        self.model=ModelResponses([]);self.requests=[];self.images=[]
        async def chat(request):
            body=await request.json();cid=request.match_info['cid'];self.requests.append((cid,body['model']))
            if cid=='vision':
                self.assertFalse(body.get('tools'),'Observer must never receive tool execution rights')
                pixels=[p for m in body['messages'] if isinstance(m.get('content'),list) for p in m['content'] if p.get('type')=='image_url']
                self.assertEqual(len(pixels),1)
                raw=base64.b64decode(pixels[0]['image_url']['url'].split(',')[1]);self.assertTrue(raw.startswith(b'\xff\xd8'))
                self.images.append({'bytes':len(raw),'model':body['model'],'connection':cid})
                choice=ProviderChunk(content='{"observations":["Controlled Electron fixture; use independent UIA assertions"],"errors":[]}',done=True)
            else:
                self.model.seen.append(body['messages']);choice=self.model.next(body['messages'])
                if choice=='block':
                    self.model.blocked.set();await self.model.release.wait();choice=ProviderChunk(content='Released',done=True)
            message={'role':'assistant','content':choice.content or ''}
            if choice.tool_calls:
                message['tool_calls']=[{'id':'m5_'+str(len(self.requests))+'_'+str(i),'type':'function','function':{'name':c.name,'arguments':json.dumps(c.arguments)}} for i,c in enumerate(choice.tool_calls)]
            return web.json_response({'choices':[{'message':message,'finish_reason':'tool_calls' if choice.tool_calls else 'stop'}], 'usage':{'prompt_tokens':20,'completion_tokens':5}})
        app=web.Application(client_max_size=8*1024*1024);app.router.add_post('/{cid}/v1/chat/completions',chat)
        self.http=web.AppRunner(app,handler_cancellation=True);await self.http.setup()
        site=web.TCPSite(self.http,'127.0.0.1',0);await site.start();port=site._server.sockets[0].getsockname()[1]
        connections=[{'connection_id':cid,'display_name':'M5 HTTP '+cid,'provider_type':'openai_compatible','base_url':f'http://127.0.0.1:{port}/{cid}/v1','credential_reference':'connection-'+cid,'enabled':True} for cid in ('coder','vision')]
        profiles=[{'model_profile_id':cid,'connection_id':cid,'model_id':'m5-'+cid,'display_name':cid,'supports_vision':cid=='vision','context_window':262144,'max_output_tokens':4096} for cid in ('coder','vision')]
        self.config=validate_config({'strategy':'single-agent','roles':{'executor':{'model_profile_id':'coder'}},'vision_profile_id':'vision','budget':{'api_calls':100,'api_tokens':1000000,'global_api_calls':200,'global_api_tokens':4000000,'local_repairs':3}})
        self.server.tasks.credentials={'connection-coder':'mock-only-coder','connection-vision':'mock-only-vision'}
        await self.server.tasks.handle(self.client,{'type':'task.catalog.update','payload':{'catalog':{'connections':connections,'profiles':profiles},'config':self.config,'chat_default':'coder'}},set())
        self.assertEqual(self.client.messages[-1]['type'],'task.loaded',self.client.messages[-1])

    async def asyncTearDown(self):
        tasks=self.server.tasks.runtime.list(self.thread.id)
        if tasks:
            (ROOT/'validation-reports').mkdir(exist_ok=True)
            execution=self.server.store.connection.execute('SELECT data_json FROM agent_execution_runs WHERE id=?',(tasks[0]['id'],)).fetchone()
            (ROOT/('validation-reports/m5-debug-'+self._testMethodName+'.json')).write_text(json.dumps({'task':self.server.tasks.public(tasks[0]),'execution':json.loads(execution[0]) if execution else None,'tools':[e['payload'] for e in self.client.messages if e['type']=='tool.completed']},ensure_ascii=False,indent=2),encoding='utf-8')
        self.model.release.set()
        for run in list(self.server.active_turns.values()):run.cancel()
        await asyncio.gather(*list(self.server.active_turns.values()),return_exceptions=True)
        await self.server.close_async();self.server.close();await self.http.cleanup()
        self.env.stop();self.temp.cleanup()

    async def drain(self):
        await asyncio.wait_for(asyncio.gather(*list(self.server.active_turns.values())),600)

    async def start(self,steps):
        self.model.steps=list(steps)
        await self.server.tasks.handle(self.client,{'type':'task.start','thread_id':self.thread.id,'payload':{'goal':'检查 Electron Settings，修复输入框及保存状态；运行测试、启动程序、操作和截图；根据独立失败证据继续修复，保持验收契约不变。','config':self.config}},set())
        self.assertTrue(self.server.active_turns,self.client.messages[-1]);await self.drain()
        return self.server.tasks.runtime.list(self.thread.id)[0]

    async def resume(self,task,steps,wait=True):
        self.model.steps=list(steps);self.model.blocked.clear()
        await self.server.tasks.handle(self.client,{'type':'task.resume','thread_id':self.thread.id,'payload':{'task_id':task['id'],'confirm_workspace':True}},set())
        if wait:await self.drain()

    def action(self,name,**args):
        def choose(messages,_model):return tool(name,window_id=self.window,**args)
        return choose

    def select(self,messages,_model):
        windows=last_result(messages,'desktop_list_windows')['data']['windows']
        matches=[w for w in windows if w['title']=='M5 Electron acceptance']
        self.assertEqual(len(matches),1,windows);self.window=matches[0]['window_id']
        return tool('desktop_inspect',window_id=self.window)

    def list_windows(self,messages,_model):
        lines=last_result(messages).get('stdout','').splitlines()
        ready=next((line.split('M5_ELECTRON_READY ',1)[1] for line in lines if 'M5_ELECTRON_READY ' in line),None)
        self.assertIsNotNone(ready,'Missing actual process readiness metadata')
        return tool('desktop_list_windows',pid=json.loads(ready)['pid'])

    def stop(self,messages,_model):return tool('stop_process',process_id=process_id(messages))

    async def test_actual_electron_multiround_http_gui_stop_resume_restart(self):
        def feedback(messages,_model):
            self.assertTrue('GUI acceptance' in str(messages),'Missing independent GUI feedback')
            self.assertTrue('DESKTOP_WAIT_TIMEOUT' in str(messages),'Missing structured state assertion failure')
            return tool('read_file',path='src/App.tsx')
        checks=[command('npm run typecheck'),command('npm test'),command('npm run build')]
        task=await self.start([command('npm ci --no-audit --no-fund'),tool('search_files',query='disabled',path='src'),tool('read_file',path='src/App.tsx'),
            tool('apply_patch',path='src/App.tsx',old_text='disabled={true}',new_text='disabled={false}'),*checks,
            tool('start_process',command='npm start',timeout_seconds=240),poll_ready,self.list_windows,self.select,
            self.action('desktop_wait',selector={'name':'Settings','control_type':'Button'},state='visible',seconds=5),
            self.action('desktop_click',selector={'name':'Settings','control_type':'Button'}),self.action('desktop_inspect'),
            self.action('desktop_type_text',selector={'control_type':'Edit'},text='M5 initial check'),
            self.action('desktop_click',selector={'name':'Save','control_type':'Button'},confirm_risk=True),self.action('desktop_inspect'),
            self.action('desktop_screenshot',share_with_model=True),self.stop,tool('git_diff'),ProviderChunk(content='Input repaired; independently verify saving',done=True),
            feedback,tool('apply_patch',path='src/App.tsx',old_text="setStatus('Not saved');",new_text="setStatus('Saved: '+value);"),*checks,tool('git_diff'),ProviderChunk(content='Second repair; run the frozen GUI contract',done=True)])
        failures=[{'tool':e['payload']['name'],'error':e['payload']['result'].get('error'),
                   'summary':e['payload']['result'].get('summary','')[:500]}
                  for e in self.client.messages if e['type']=='tool.completed' and not e['payload']['result'].get('ok')]
        self.assertEqual(task['status'],'awaiting_approval',{'task_error':task.get('last_error') or task['reason'],'failed_tools':failures})
        self.assertEqual((task['attempts'],task['repairs']),(2,1))
        self.assertTrue(all(v['ok'] for v in task['verification']))
        worktree=Path(task['workspace']);self.worktree=worktree
        self.assertEqual(json.loads((worktree/'.runtime/saved.json').read_text())['value'],'M5 verified B')
        self.assertIn('disabled={false}',task['report']['diff']);self.assertIn("setStatus('Saved: '+value)",task['report']['diff'])
        self.assertIn('disabled={true}',(self.source/'src/App.tsx').read_text())
        self.assertFalse(acceptance_changes(worktree,task['acceptance_baseline']))
        self.assertTrue(self.images);self.assertTrue(all(v['model']=='m5-vision' for v in self.images))
        self.assertTrue(any(cid=='coder' for cid,_ in self.requests));self.assertTrue(any(cid=='vision' for cid,_ in self.requests))
        self.assertTrue(any(c['role']=='vision-observer' for c in self.server.tasks.runtime.calls(task['id'])))
        initial_history=task['verification_history']
        self.assertFalse(initial_history[0]['passed']);self.assertTrue(initial_history[1]['passed'])
        captures=[e for r in initial_history for v in r['results'] for e in v.get('evidence',[]) if e['tool']=='desktop_screenshot' and e.get('ok')]
        self.assertGreaterEqual(len(captures),2)
        self.assertTrue(all(Path(e['path']).read_bytes().startswith(b'\x89PNG') for e in captures))
        self.assertFalse(alive(json.loads((worktree/'.runtime/process.json').read_text())['pid']))
        patches=sum(e['type']=='tool.completed' and e['payload']['name']=='apply_patch' for e in self.client.messages)
        # Pause with real owned Electron/renderer descendants alive, then resume
        # the same checkpoint without replaying either completed source patch.
        await self.resume(task,[tool('start_process',command='npm start',timeout_seconds=240),poll_ready,'block'],wait=False)
        await asyncio.wait_for(self.model.blocked.wait(),60)
        processes=json.loads((worktree/'.runtime/process.json').read_text());pid=processes['pid'];self.assertTrue(alive(pid))
        self.assertTrue(processes['children']);self.assertTrue(any(alive(child) for child in processes['children']))
        await self.server.tasks.handle(self.client,{'type':'task.pause','thread_id':self.thread.id,'payload':{'task_id':task['id']}},set())
        self.assertFalse(alive(pid));self.assertTrue(all(not alive(child) for child in processes['children']))
        paused=self.server.tasks.runtime.get(task['id']);self.assertEqual(paused['status'],'paused')
        usage=self.server.tasks.runtime.usage(task['id']);self.assertGreater(usage['api_calls'],0)
        await self.resume(task,[tool('read_file',path='src/App.tsx'),ProviderChunk(content='Retain completed changes; verify checkpoint',done=True)])
        self.assertEqual(self.server.tasks.runtime.get(task['id'])['status'],'awaiting_approval')
        self.assertEqual(sum(e['type']=='tool.completed' and e['payload']['name']=='apply_patch' for e in self.client.messages),patches)
        self.assertGreater(self.server.tasks.runtime.usage(task['id'])['api_calls'],usage['api_calls'])
        # Stop must close the entire actual controlled process tree.
        await self.resume(task,[tool('start_process',command='npm start',timeout_seconds=240),poll_ready,'block'],wait=False)
        await asyncio.wait_for(self.model.blocked.wait(),60)
        processes=json.loads((worktree/'.runtime/process.json').read_text());pid=processes['pid']
        await self.server.tasks.handle(self.client,{'type':'task.cancel','thread_id':self.thread.id,'payload':{'task_id':task['id']}},set())
        self.assertFalse(alive(pid));self.assertTrue(all(not alive(child) for child in processes['children']))
        self.assertEqual(self.server.tasks.runtime.get(task['id'])['status'],'cancelled')
        # Explicitly deny image transfer in the next GUI gate. No observer call.
        class Deny(Client):
            async def send_json(inner,event):
                inner.messages.append(event)
                if event['type']=='approval.requested':
                    denied=event['payload'].get('tool')=='desktop_screenshot' and event['payload'].get('arguments',{}).get('share_with_model')
                    inner.server.approvals.respond(event['payload']['approval_id'],'deny' if denied else 'allow_once')
        before=len(self.images);original=self.client;self.client=Deny(self.server)
        await self.resume(task,[ProviderChunk(content='Verify without bypassing approvals',done=True)])
        denied=self.server.tasks.runtime.get(task['id']);self.assertEqual(denied['status'],'paused')
        self.assertEqual(denied['verification'][-1]['error_code'],'APPROVAL_DENIED');self.assertEqual(len(self.images),before)
        self.client=original
        usage=self.server.tasks.runtime.usage(task['id'])
        await self.server.close_async();self.server.close();self.server=AgentServer('fixture')
        restored=self.server.tasks.runtime.get(task['id'])
        self.assertEqual(restored['status'],'paused');self.assertEqual(restored['resolved_roles']['executor']['model_profile_id'],'coder')
        self.assertEqual(restored['resolved_vision']['model_profile_id'],'vision')
        self.assertEqual(self.server.tasks.runtime.usage(task['id']),usage)
        self.assertEqual(self.server.tasks.catalog().load()['profiles'][0]['model_profile_id'],'coder')
        restored_project=self.server.projects.active
        self.assertEqual(Path(restored_project.workspace.root),self.source)
        self.assertEqual(restored_project.state.get_thread(self.thread.id).active_model,'profile:coder')
        self.assertTrue(self.server.store.task_plans.executions(task['id']))
        report={'real_gui':True,'mock_scope':'model decisions via localhost HTTP only','real_online_inference':'NOT RUN',
            'repair_attempts':2,'additional_repairs':1,'verification':initial_history,'diff':task['report']['diff'],
            'image_transports':self.images,'requests':self.requests,'pause_resume_no_replay':True,'stop_pid_dead':True,'upload_denial':True,'restart_snapshot_retained':True}
        (ROOT/'validation-reports').mkdir(exist_ok=True)
        (ROOT/'validation-reports/m5-electron-e2e.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')

    async def test_changing_gui_launcher_cannot_forge_acceptance(self):
        text=(self.source/'package.json').read_text()
        task=await self.start([tool('apply_patch',path='package.json',old_text='node launch.cjs',new_text='node fake.cjs'),ProviderChunk(content='All passed',done=True)])
        self.assertEqual(task['status'],'paused',task['reason'])
        self.assertEqual(task['last_error']['code'],'ACCEPTANCE_CONTRACT_CHANGED')
        self.assertEqual(task['verification'][-1]['category'],'configuration')
        self.assertEqual(self.images,[])
        self.assertIn('node launch.cjs',text)
