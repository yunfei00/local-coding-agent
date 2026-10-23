"""Real WinForms + Windows UIA/SendInput/PrintWindow. Only model decisions are scripted."""
import asyncio
import base64
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from agent.desktop.runtime import DesktopRuntime, NAMES, public_arguments
from agent.tools.base import ToolError
from agent.tools.registry import ToolRegistry
from agent.tools.workspace import Workspace
from agent.permissions.policy import PermissionMode, PermissionPolicy
from agent.llm.openai_compatible import OpenAICompatibleProvider
from agent.llm.ollama import OllamaProvider
from agent.llm.base import ProviderChunk, ToolCall
from agent.llm.router import validate_config
from agent.server.main import AgentServer
from test_m2_processes import alive, wait_file
from test_m2_projects import Client, ModelResponses, tool, last_result, poll_ready

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT/'manual-fixtures/m3-windows-gui/app.ps1'


class DesktopContractTests(unittest.IsolatedAsyncioTestCase):
    @unittest.skipUnless(sys.platform=='win32','Actual Windows session API')
    async def test_actual_session_guard_denies_locked_session(self):
        from agent.desktop.session import require_interactive_session
        try:
            require_interactive_session()
        except ToolError as exc:
            self.assertIn(exc.code,{'DESKTOP_SESSION_LOCKED','DESKTOP_SESSION_UNAVAILABLE'})
            with self.assertRaises(ToolError) as error:
                await DesktopRuntime().execute('desktop_list_windows',{},owner='locked-test',authorized=True)
            self.assertEqual(error.exception.code,exc.code)

    async def test_default_deny_and_read_only(self):
        with tempfile.TemporaryDirectory() as directory:
            registry = ToolRegistry(Workspace(directory))
            for name in NAMES:
                self.assertIn(name, registry.names)
                with self.assertRaises(ToolError) as error:
                    await registry.execute(name, {}, owner_id='owner')
                self.assertEqual(error.exception.code,'DESKTOP_CONSENT_REQUIRED')
                verdict = PermissionPolicy().evaluate(tool_name=name,arguments={},workspace=Workspace(directory))
                self.assertTrue(verdict.requires_approval)
            names={s['function']['name'] for s in registry.schemas(desktop_owner_id='plain')}
            self.assertEqual(names & set(NAMES),{'desktop_list_windows'})
            self.assertFalse(set(NAMES) & set(PermissionPolicy(PermissionMode.READ_ONLY).visible_tools(registry.names)))

    async def test_non_windows_explicitly_unsupported(self):
        if sys.platform == 'win32':
            self.skipTest('Non-Windows contract; no platform/API mock')
        with self.assertRaises(ToolError) as error:
            await DesktopRuntime().execute('desktop_list_windows',{},owner='x',authorized=True)
        self.assertEqual(error.exception.code,'DESKTOP_UNSUPPORTED')

    async def test_scope_and_redacted_input_contract(self):
        runtime = DesktopRuntime()
        runtime.windows['one']={'owner':'a','native':{}}
        with self.assertRaises(ToolError):
            runtime.binding('one','b')
        await runtime.close_owner('a')
        with self.assertRaises(ToolError):
            runtime.binding('one','a')
        self.assertEqual(public_arguments('desktop_type_text',{'text':'ordinary fixture text'})['text'],'[input omitted]')
        args={'window_id':'one','share_with_model':True}
        with tempfile.TemporaryDirectory() as directory:
            verdict=PermissionPolicy(PermissionMode.FULL_ACCESS).evaluate(tool_name='desktop_screenshot',arguments=args,workspace=Workspace(directory))
            self.assertTrue(verdict.requires_approval)
            self.assertIn('第三方',verdict.reason)

    async def test_real_image_protocol_not_text_ocr(self):
        content=[{'type':'text','text':'Actual image'},{'type':'image_url','image_url':{'url':'data:image/jpeg;base64,aGVsbG8=','detail':'low'}}]
        messages=[{'role':'user','content':content}]
        self.assertEqual(OpenAICompatibleProvider._wire_messages(messages)[0]['content'],content)
        native=OllamaProvider._wire_messages(messages)[0]
        self.assertEqual(native['images'],['aGVsbG8='])
        self.assertEqual(native['content'],'Actual image')


@unittest.skipUnless(sys.platform == 'win32', 'Windows GUI requires real Windows desktop APIs')
class WindowsDesktopTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        from windows_desktop_support import require_test_desktop
        require_test_desktop()
        self.temp=tempfile.TemporaryDirectory(prefix='m3-gui-')
        self.directory=Path(self.temp.name)
        self.env=patch.dict(os.environ,{'LCA_DATA_DIR':str(self.directory/'data'),'LCA_OPENAI_API_KEY':''})
        self.env.start()
        self.registry=ToolRegistry(Workspace(self.directory))
        self.owner='fixture-turn'
        self.statepath=self.directory/'state.json'
        self.title='M3 fixture '+self.directory.name
        self.command=f'powershell.exe -NoProfile -STA -File "{FIXTURE}" -StatePath "{self.statepath}" -Title "{self.title}"'
        self.process=await self.registry.processes.launch({'command':self.command,'timeout_seconds':180},owner=self.owner)
        try:
            await wait_file(self.statepath)
            self.state=self.state_data()
            result=await self.call('desktop_list_windows',pid=self.state['pid'])
            self.assertEqual(len(result.data['windows']),1, result.data)
            self.window=result.data['windows'][0]['window_id']
        except BaseException:
            await self.registry.processes.close()
            self.env.stop(); self.temp.cleanup()
            raise

    def state_data(self):
        return json.loads(self.statepath.read_text(encoding='utf-8-sig'))

    async def asyncTearDown(self):
        await self.registry.desktop.close_owner(self.owner)
        await self.registry.processes.close()
        if hasattr(self,'state'):
            self.assertFalse(alive(self.state['pid']))
        self.assertFalse(self.registry.desktop.workers)
        self.env.stop(); self.temp.cleanup()

    async def call(self,name,**arguments):
        if name!='desktop_list_windows':
            arguments.setdefault('window_id',getattr(self,'window',None))
        return await self.registry.execute(name,arguments,owner_id=self.owner,desktop_authorized=True,supports_vision=True)

    async def test_real_controls_screenshot_click_type_shortcut_scroll_wait(self):
        result=await self.call('desktop_inspect')
        names={c['automation_id'] for c in result.data['controls']}
        self.assertTrue({'SettingsButton','NameInput','PasswordInput','ScrollPanel'}<=names, result.data)
        ids={tuple(c['runtime_id']) for c in result.data['controls']}
        self.assertTrue(any(c['parent_runtime_id'] for c in result.data['controls']))
        self.assertTrue(all(tuple(c['parent_runtime_id']) in ids for c in result.data['controls'] if c['parent_runtime_id']))
        await self.call('desktop_focus_window')
        before=await self.call('desktop_screenshot')
        self.assertIsNone(self.registry.desktop.image_message(self.owner))
        self.assertGreaterEqual(before.data['redacted_controls'],2)
        await self.call('desktop_click',selector={'automation_id':'SettingsButton'})
        await self.call('desktop_type_text',selector={'automation_id':'NameInput'},text='M3 real input 中文')
        self.assertEqual(self.state_data()['text'],'M3 real input 中文')
        await self.call('desktop_keypress',selector={'automation_id':'NameInput'},keys='CTRL+A')
        await self.call('desktop_keypress',selector={'automation_id':'NameInput'},keys='CTRL+K',confirm_risk=True)
        await self.call('desktop_wait',selector={'automation_id':'StatusLabel'},state='name',expected='Shortcut OK')
        self.assertEqual(self.state_data()['shortcuts'],1)
        await self.call('desktop_scroll',selector={'automation_id':'ScrollPanel'},direction='down',amount=3,confirm_risk=True)
        await asyncio.sleep(.3)
        self.assertGreater(self.state_data()['scroll'],0)
        await self.call('desktop_click',selector={'automation_id':'DelayedButton'})
        await self.call('desktop_wait',selector={'automation_id':'StatusLabel'},state='name',expected='Ready after timer',seconds=5)
        after=await self.call('desktop_screenshot',share_with_model=True)
        self.assertEqual(after.data['vision_feedback'],'image_attached')
        from PIL import Image, ImageChops
        with Image.open(before.data['path']) as b, Image.open(after.data['path']) as a:
            self.assertIsNotNone(ImageChops.difference(a,b).getbbox())
            self.assertNotEqual(a.getpixel((a.width-5,a.height-5)),(0,0,0),'DPI-unaware GDI capture must fill the physical client, not leave black padding')
            for control in result.data['controls']:
                if control['automation_id'] in ('NameInput','PasswordInput'):
                    x0,y0,x1,y1=control['bounds']
                    ox,oy=after.data['origin']
                    region=a.crop((x0-ox+2,y0-oy+2,x1-ox-2,y1-oy-2))
                    if control['automation_id'] == 'PasswordInput':
                        self.assertEqual(region.getextrema(),((0,0),(0,0),(0,0)),
                                         'Sensitive input pixels must remain black')
                    else:
                        self.assertEqual(region.getpixel((max(0, region.width-5), max(0, region.height-5))), (246,246,246),
                                         'Ordinary editor contents must be concealed with a light placeholder')
            shutil.copy2(after.data['path'],ROOT/'validation-reports/m3-fixture-sanitized.png')
        image=self.registry.desktop.image_message(self.owner)['content'][1]['image_url']['url']
        self.assertTrue(base64.b64decode(image.split(',',1)[1]).startswith(b'\xff\xd8'))
        # Actual Windows capture -> actual JPEG -> original HTTP client -> local
        # Mock model endpoint. Pixels are never replaced with a generated fixture.
        from aiohttp import web
        received=[]
        async def vision_http(request):
            body=await request.json(); received.append(body)
            jpeg=body['messages'][0]['content'][1]['image_url']['url']
            self.assertEqual(jpeg,image)
            self.assertEqual(body['model'],'controlled-vision')
            self.assertEqual(request.headers.get('Authorization'),'Bearer mock-vision-only')
            return web.json_response({'choices':[{'message':{'content':'Controlled window observed'},'finish_reason':'stop'}]})
        app=web.Application();app.router.add_post('/v1/chat/completions',vision_http)
        runner=web.AppRunner(app);await runner.setup()
        try:
            site=web.TCPSite(runner,'127.0.0.1',0);await site.start()
            provider=OpenAICompatibleProvider(base_url=f'http://127.0.0.1:{site._server.sockets[0].getsockname()[1]}/v1',api_key='mock-vision-only')
            message=self.registry.desktop.image_message(self.owner,consume=True)
            async for _ in provider.stream_chat(model='controlled-vision',messages=[message]): pass
            self.assertEqual(len(received),1)
            self.assertIsNone(self.registry.desktop.image_message(self.owner,consume=True))
        finally:
            await runner.cleanup()
        screen=await self.call('desktop_screenshot',scope='screen')
        self.assertGreaterEqual(screen.data['width'],after.data['width'])
        report={'tools':list(NAMES),'actual_gui_pid_exits_in_teardown':self.state['pid'],'capture_dimensions':[after.data['width'],after.data['height']], 'redacted_controls':after.data['redacted_controls'],'real_controls':len(result.data['controls']),'scroll':self.state_data()['scroll'],'shortcut_count':self.state_data()['shortcuts'],'vision':'actual JPEG bytes, not OCR','screenshots_committed':False}
        (ROOT/'validation-reports').mkdir(exist_ok=True)
        (ROOT/'validation-reports/m3-windows-gui.json').write_text(json.dumps(report,indent=2),encoding='utf-8')

    async def test_sensitive_ambiguous_and_risky_targets_fail_closed(self):
        for name,args,code in [
            ('desktop_type_text',{'selector':{'automation_id':'PasswordInput'},'text':'fixture'},'DESKTOP_SENSITIVE_CONTROL'),
            ('desktop_keypress',{'keys':'ALT+ESCAPE','confirm_risk':True},'DESKTOP_KEYS_FORBIDDEN'),
            ('desktop_click',{'selector':{'control_type':'Button'}},'DESKTOP_SELECTOR_AMBIGUOUS'),
            ('desktop_click',{'selector':{'automation_id':'DeleteButton'}},'DESKTOP_RISK_APPROVAL_REQUIRED')]:
            with self.assertRaises(ToolError) as error:
                await self.call(name,**args)
            self.assertEqual(error.exception.code,code)
        self.assertEqual(self.state_data()['dangerous'],0)
        with self.assertRaises(ToolError) as error:
            await self.call('desktop_wait',selector={'automation_id':'Absent'},seconds=.2)
        self.assertEqual(error.exception.code,'DESKTOP_WAIT_TIMEOUT')

    async def test_cancel_and_timeout_kill_worker_without_later_actions(self):
        pending=asyncio.create_task(self.call('desktop_wait',selector={'automation_id':'Absent'},seconds=30,timeout_seconds=40))
        while not self.registry.desktop.workers:
            await asyncio.sleep(.01)
        pids=[p.pid for p in self.registry.desktop.workers]
        pending.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await pending
        self.assertFalse(any(alive(pid) for pid in pids))
        self.assertFalse(self.registry.desktop.workers)
        with self.assertRaises(ToolError) as error:
            await self.call('desktop_wait',selector={'automation_id':'Absent'},seconds=30,timeout_seconds=.2)
        self.assertEqual(error.exception.code,'DESKTOP_TIMEOUT')
        self.assertEqual(self.state_data()['clicks'],0)

    async def test_single_agent_task_actual_gui_image_feedback_and_cancel(self):
        source=self.directory/'repo'
        source.mkdir()
        (source/'README.md').write_text('M3 real GUI task fixture',encoding='utf-8')
        for args in (['init','-q','-b','main'],['config','user.name','M3 fixture'],['config','user.email','m3@example.test'],['add','.'],['commit','-qm','fixture']):
            subprocess.run(['git',*args],cwd=source,check=True,capture_output=True)
        server=AgentServer('fixture')
        server.permissions.set_mode('full_access')
        # Force the same real GUI task across slices; its process, authorization,
        # handles and observations must survive without replaying UI actions.
        server.max_model_steps=6
        client=Client(server)
        project,thread,_=server.projects.open(source,active_model='single-executor')
        state=self.directory/'agent-state.json'
        title=self.title+' Agent'
        command=f'powershell.exe -NoProfile -STA -File "{FIXTURE}" -StatePath "{state}" -Title "{title}"'
        selected={}
        def list_windows(messages,model):
            return tool('desktop_list_windows',pid=json.loads(state.read_text(encoding='utf-8-sig'))['pid'])
        def select(messages,model):
            windows=last_result(messages,'desktop_list_windows')['data']['windows']
            self.assertEqual(len(windows),1)
            selected.update(window_id=windows[0]['window_id'])
            return tool('desktop_inspect',**selected)
        def action(name,**arguments):
            return lambda messages,model:tool(name,**selected,**arguments)
        def inspect_image(messages,model):
            image_messages=[m for m in messages if isinstance(m.get('content'),list)]
            self.assertTrue(image_messages,'Actual pixels must reach the model, not just a path/OCR')
            image=image_messages[-1]['content'][1]['image_url']['url']
            self.assertTrue(base64.b64decode(image.split(',',1)[1]).startswith(b'\xff\xd8'))
            self.assertEqual(last_result(messages,'desktop_screenshot')['data']['vision_feedback'],'image_attached')
            return tool('git_diff')
        initial=[tool('start_process',command=command,timeout_seconds=180),poll_ready,list_windows,select,
            action('desktop_focus_window'),action('desktop_click',selector={'automation_id':'SettingsButton'}),
            action('desktop_type_text',selector={'automation_id':'NameInput'},text='Agent real input'),
            action('desktop_keypress',selector={'automation_id':'NameInput'},keys='CTRL+K',confirm_risk=True),
            action('desktop_scroll',selector={'automation_id':'ScrollPanel'},direction='down',amount=2,confirm_risk=True),
            action('desktop_wait',selector={'automation_id':'StatusLabel'},state='name',expected='Shortcut OK'),
            action('desktop_screenshot',share_with_model=True),inspect_image,ProviderChunk(content='Actual controls and screenshot verified',done=True)]
        model=ModelResponses(initial)
        model.supports_vision=True
        server.tasks.provider_factory_override=lambda *_:model
        check=f'uv run --no-project python -c "import json; s=json.load(open(r\'{state}\')); assert s[\'clicks\']==1 and s[\'text\']==\'Agent real input\' and s[\'shortcuts\']==1 and s[\'scroll\']>0; print(\'Actual GUI state verified\')"'
        config=validate_config({'strategy':'single-agent','roles':{'executor':{'model':'single-executor','context_window':262144,'output_limit':4096}},'budget':{'api_calls':50,'api_tokens':4000000,'global_api_calls':100,'global_api_tokens':9000000},'verification_commands':[check,'git diff --check']})
        try:
            await server.tasks.handle(client,{'type':'task.settings.update','payload':{'config':config}},set())
            await server.tasks.handle(client,{'type':'task.start','thread_id':thread.id,'payload':{'goal':'Launch the GUI fixture, click Settings, type ordinary text, use the shortcut, scroll and verify actual controls and screenshot.','config':config}},set())
            await asyncio.wait_for(asyncio.gather(*list(server.active_turns.values())),180)
            task=server.store.task_runtime.list(thread.id)[0]
            self.assertEqual(task['status'],'awaiting_approval',task.get('last_error') or task.get('reason'))
            self.assertTrue(all(v['ok'] for v in task['verification']))
            self.assertTrue(any(e['type']=='turn.continuing' for e in client.messages))
            self.assertEqual(sum(e['type']=='tool.completed' and e['payload']['name']=='start_process' for e in client.messages),1)
            captures=[e['metadata'] for e in server.store.task_plans.executions(task['id']) if e['tool']=='desktop_screenshot']
            self.assertEqual(len(captures),1)
            self.assertEqual(len(captures[0]['sha256']),64)
            pid=json.loads(state.read_text(encoding='utf-8-sig'))['pid']
            self.assertFalse(alive(pid),'Normal model finish must clean the actual GUI')
            self.assertTrue(any(e['type']=='approval.requested' and '第三方' in e['payload']['reason'] for e in client.messages))
            input_events=[e for e in client.messages if e['type'] in ('tool.requested','tool.started','approval.requested') and e['payload'].get('name',e['payload'].get('tool'))=='desktop_type_text']
            self.assertTrue(input_events)
            self.assertTrue(all(e['payload']['arguments']['text']=='[input omitted]' for e in input_events))
            model.steps=[tool('start_process',command=command,timeout_seconds=180),poll_ready,list_windows,select,
                         action('desktop_wait',selector={'automation_id':'Absent'},seconds=30,timeout_seconds=40)]
            await server.tasks.handle(client,{'type':'task.resume','thread_id':thread.id,'payload':{'task_id':task['id'],'confirm_workspace':True}},set())
            deadline=time.monotonic()+40
            while time.monotonic()<deadline:
                if any(e['type']=='tool.started' and e['payload']['name']=='desktop_wait' and e['payload']['arguments'].get('selector',{}).get('automation_id')=='Absent' for e in client.messages):
                    break
                await asyncio.sleep(.05)
            else:
                self.fail('Agent did not start the real cancellable UI wait')
            await server.tasks.handle(client,{'type':'task.cancel','thread_id':thread.id,'payload':{'task_id':task['id']}},set())
            await asyncio.gather(*list(server.active_turns.values()),return_exceptions=True)
            self.assertEqual(server.store.task_runtime.get(task['id'])['status'],'cancelled')
            self.assertFalse(alive(json.loads(state.read_text(encoding='utf-8-sig'))['pid']))
            report={'single_agent':True,'planning_attempts':task.get('planning_attempts',0),'actual_tools':[e['payload']['name'] for e in client.messages if e['type']=='tool.completed'],'verification':task['verification'],'artifact_refs':captures,'cancelled_task':True,'real_image_feedback':True,'screenshots_uploaded_by_ci':False}
            (ROOT/'validation-reports/m3-single-agent.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
        finally:
            for running in list(server.active_turns.values()):
                running.cancel()
            await asyncio.gather(*list(server.active_turns.values()),return_exceptions=True)
            await server.close_async()
            server.close()

    async def test_window_move_coordinate_fallback_and_nonvisual_capture(self):
        import win32gui
        import ctypes
        user=ctypes.WinDLL('user32')
        user.SetThreadDpiAwarenessContext.argtypes=[ctypes.c_void_p]
        user.SetThreadDpiAwarenessContext.restype=ctypes.c_void_p
        old_context=user.SetThreadDpiAwarenessContext(ctypes.c_void_p(-4))
        before=await self.call('desktop_inspect')
        old=next(c for c in before.data['controls'] if c['automation_id']=='SettingsButton')['bounds']
        win32gui.MoveWindow(self.state['hwnd'],180,120,660,680,True)
        # This test owns the fixture. Keep only its window above unrelated
        # desktop windows; production coordinate input must still reject cover.
        import win32con
        win32gui.SetWindowPos(self.state['hwnd'],win32con.HWND_TOPMOST,0,0,0,0,
                             win32con.SWP_NOMOVE|win32con.SWP_NOSIZE)
        after=await self.call('desktop_inspect')
        bounds=next(c for c in after.data['controls'] if c['automation_id']=='SettingsButton')['bounds']
        self.assertNotEqual(old,bounds)
        x,y=win32gui.ScreenToClient(self.state['hwnd'],((bounds[0]+bounds[2])//2,(bounds[1]+bounds[3])//2))
        user.SetThreadDpiAwarenessContext(old_context)
        await self.call('desktop_click',method='coordinate',x=x,y=y,confirm_risk=True)
        await self.call('desktop_wait',selector={'automation_id':'NameInput'},state='enabled')
        self.assertEqual(self.state_data()['clicks'],1)
        capture=await self.registry.execute('desktop_screenshot',{'window_id':self.window,'share_with_model':True},owner_id=self.owner,desktop_authorized=True,supports_vision=False)
        self.assertIn('not_vision_capable',capture.data['vision_feedback'])
        self.assertIsNone(self.registry.desktop.image_message(self.owner))
        self.assertGreater(capture.data['dpi'],0)
        win32gui.SetWindowText(self.state['hwnd'],'')
        listed=await self.call('desktop_list_windows',pid=self.state['pid'])
        self.assertTrue(any(w['window_id']==self.window and w['title']=='' for w in listed.data['windows']),'Untitled GUI windows must remain addressable by stable identity')
        await self.registry.processes.close_owner(self.owner)
        with self.assertRaises(ToolError) as error:
            await self.call('desktop_inspect')
        self.assertEqual(error.exception.code,'DESKTOP_WINDOW_STALE')

    async def test_denied_desktop_approval_never_clicks_real_window(self):
        server=AgentServer('fixture')
        server.permissions.set_mode('full_access')
        class Deny:
            async def send_json(inner,event):
                if event['type']=='approval.requested':
                    server.approvals.respond(event['payload']['approval_id'],'deny')
        try:
            result=await server._authorize_tool(Deny(),project=SimpleNamespace(workspace=self.registry.processes.workspace,tools=self.registry),
                call=ToolCall('desktop_click',{'window_id':self.window,'selector':{'automation_id':'SettingsButton'}}),
                call_id='deny',thread_id='thread',turn_id=self.owner,user_prompt='Operate only the fixture')
            self.assertEqual(result['error']['code'],'APPROVAL_DENIED')
            self.assertEqual(self.state_data()['clicks'],0)
        finally:
            await server.close_async()
            server.close()
