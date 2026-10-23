"""Actual WinForms failure -> original Single Agent -> patch -> independent GUI gate."""
import asyncio
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from agent.core.gui_verification import validate_gui
from agent.llm.base import ProviderChunk
from agent.llm.router import validate_config
from agent.server.main import AgentServer
from test_m2_projects import Client, ModelResponses, tool
from test_m2_processes import alive

ROOT=Path(__file__).resolve().parents[1]


class GUIContractTests(unittest.TestCase):
    def test_gui_overrides_discovery_and_frozen_value_are_independent_of_file_edits(self):
        from agent.core.gui_verification import discover_gui
        from agent.llm.router import apply_config_overrides
        contract={'command':'npm start','window_title':'fixture','steps':[{'tool':'desktop_wait','arguments':{'selector':{'automation_id':'Status'},'state':'name','expected':'Ready'}}]}
        config=apply_config_overrides(validate_config(),{'gui_verification':contract})
        self.assertEqual(config['gui_verification']['command'],'npm start')
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);(root/'.lca').mkdir()
            path=root/'.lca/gui-verification.json';path.write_text(json.dumps(contract))
            frozen=discover_gui(root,None)
            path.write_text('{}')
            self.assertEqual(frozen['steps'][0]['arguments']['expected'],'Ready')
            with self.assertRaises(ValueError): discover_gui(root,None)

    def test_missing_assertion_or_model_controlled_window_rejected(self):
        for text,selector in (('password=fixture',{'automation_id':'NameInput'}),('ordinary',{'automation_id':'PasswordInput'})):
            steps=[{'tool':'desktop_type_text','arguments':{'text':text,'selector':selector}},{'tool':'desktop_wait','arguments':{'selector':{'automation_id':'Status'},'state':'visible'}}]
            with self.assertRaises(ValueError):
                validate_gui({'command':'npm start','window_title':'fixture','steps':steps})
        for steps in ([{'tool':'desktop_click','arguments':{}}], [{'tool':'desktop_wait','arguments':{'window_id':'foreign','state':'name','expected':'ok'}}]):
            with self.assertRaises(ValueError):
                validate_gui({'command':'npm start','window_title':'fixture','steps':steps})


@unittest.skipUnless(sys.platform=='win32','Real Windows interactive GUI required; desktop APIs are never mocked')
class AutonomousGUIRepairTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        from windows_desktop_support import require_test_desktop
        require_test_desktop()
        (ROOT/'validation-reports').mkdir(exist_ok=True)
        self.temp=tempfile.TemporaryDirectory(prefix='m4-gui-')
        self.root=Path(self.temp.name)
        self.env=patch.dict(os.environ,{'LCA_DATA_DIR':str(self.root/'data'),'LCA_OPENAI_API_KEY':''})
        self.env.start()
        self.source=self.root/'repo';self.source.mkdir()
        shutil.copy2(ROOT/'manual-fixtures/m3-windows-gui/app.ps1',self.source/'app.ps1')
        scenario=json.loads((ROOT/'manual-fixtures/m4-gui-repair/scenario.json').read_text(encoding='utf-8'))
        source=(self.source/'app.ps1').read_text(encoding='utf-8').replace(scenario['initial_old'],scenario['initial_new'])
        (self.source/'app.ps1').write_text(source,encoding='utf-8')
        (self.source/'tests').mkdir()
        (self.source/'tests/test_source.py').write_text('import unittest\nfrom pathlib import Path\nclass Source(unittest.TestCase):\n def test_entry_point(self): self.assertIn("Application]::Run",Path("app.ps1").read_text())\n',encoding='utf-8')
        (self.source/'.gitignore').write_text('__pycache__/\n.venv/\n',encoding='utf-8')
        for args in (['init','-q','-b','main'],['config','user.name','M4 fixture'],['config','user.email','m4@example.test'],['add','.'],['commit','-qm','fixture']):
            subprocess.run(['git',*args],cwd=self.source,check=True,capture_output=True)
        self.server=AgentServer('fixture');self.server.permissions.set_mode('full_access')
        self.client=Client(self.server)
        self.project,self.thread,_=self.server.projects.open(self.source,active_model='single-executor')
        self.state=self.root/'state.json'
        self.title='M4 fixture '+self.root.name
        self.gui={'command':f'powershell.exe -NoProfile -STA -File app.ps1 -StatePath "{self.state}" -Title "{self.title}"','window_title':self.title,'timeout_seconds':90,'steps':[
            {'tool':'desktop_click','arguments':{'selector':{'automation_id':'SettingsButton'}}},
            {'tool':'desktop_wait','arguments':{'selector':{'automation_id':'StatusLabel'},'state':'name','expected':'Settings ready','seconds':.3}},
            {'tool':'desktop_wait','arguments':{'selector':{'automation_id':'NameInput'},'state':'enabled','seconds':.3}},
            {'tool':'desktop_type_text','arguments':{'selector':{'automation_id':'NameInput'},'text':'M4 validated'}}]}

    async def asyncTearDown(self):
        for task in list(self.server.active_turns.values()): task.cancel()
        await asyncio.gather(*list(self.server.active_turns.values()),return_exceptions=True)
        await self.server.close_async();self.server.close()
        # Each completed/cancelled round must actually release the WinForms process.
        if self.state.exists():
            state=json.loads(self.state.read_text(encoding='utf-8-sig'))
            self.assertFalse(alive(state['pid']), 'GUI process leaked')
        self.env.stop();self.temp.cleanup()

    async def start(self, steps, repairs=3, client=None, wait=True):
        self.model=ModelResponses(steps)
        self.server.tasks.provider_factory_override=lambda *_:self.model
        config=validate_config({'strategy':'single-agent','roles':{'executor':{'model':'single-executor','context_window':262144,'output_limit':4096}},'budget':{'api_calls':50,'api_tokens':4000000,'global_api_calls':100,'global_api_tokens':9000000,'local_repairs':repairs},'verification_commands':['uv run --no-project python -m unittest discover -s tests -v','git diff --check'],'gui_verification':self.gui})
        await self.server.tasks.handle(client or self.client,{'type':'task.start','thread_id':self.thread.id,'payload':{'goal':'Fix Settings page; independent GUI contract must pass. Do not weaken assertions.','config':config}},set())
        self.assertTrue(self.server.active_turns,(client or self.client).messages[-1])
        if wait:
            await asyncio.wait_for(asyncio.gather(*list(self.server.active_turns.values())),210)
        return self.server.store.task_runtime.list(self.thread.id)[0]

    async def test_real_multiround_repair_source_build_gui_diff(self):
        def feedback(messages,model):
            text=str(messages)
            self.assertIn('GUI acceptance',text)
            self.assertIn('DESKTOP_WAIT_TIMEOUT',text)
            return tool('read_file',path='app.ps1')
        task=await self.start([tool('read_file',path='app.ps1'),
            tool('apply_patch',path='app.ps1',old_text='Status.Text="Settings broken"',new_text='Status.Text="Settings ready"'),
            ProviderChunk(content='First repair; independently check input state',done=True),
            feedback,tool('apply_patch',path='app.ps1',old_text='Clicks++;Entry.Enabled=false',new_text='Clicks++;Entry.Enabled=true'),
            tool('git_diff'),ProviderChunk(content='Input activation repaired; verify real UI',done=True)])
        self.assertEqual(task['status'],'awaiting_approval',task['reason'])
        self.assertEqual(task['attempts'],2)
        self.assertEqual(task['repairs'],1)
        self.assertTrue(all(r['ok'] for r in task['verification']))
        self.assertEqual(task.get('planning_attempts',0),0)
        state=json.loads(self.state.read_text(encoding='utf-8-sig'))
        self.assertEqual(state['text'],'M4 validated')
        self.assertEqual(state['status'],'Settings ready')
        self.assertIn('Entry.Enabled=true',task['report']['diff'])
        self.assertFalse(subprocess.check_output(['git','status','--porcelain'],cwd=self.source,text=True))
        captures=[e for e in task['verification'][-1]['evidence'] if e['tool']=='desktop_screenshot']
        self.assertEqual(len(captures),1)
        self.assertTrue(Path(captures[0]['path']).read_bytes().startswith(b'\x89PNG'))
        shutil.copy2(captures[0]['path'],ROOT/'validation-reports/m4-fixture-sanitized.png')
        report={'real_gui':True,'mock_scope':'model decisions only','attempts':task['attempts'],'repairs':task['repairs'],'verification':task['verification'],'diff':task['report']['diff'],'final_state':state,'process_alive':alive(state['pid'])}
        (ROOT/'validation-reports/m4-autonomous-gui.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')

    async def test_exhausted_repairs_cannot_self_declare_success(self):
        task=await self.start([ProviderChunk(content='Everything passed!',done=True)],repairs=0)
        self.assertEqual(task['status'],'paused',task['reason'])
        self.assertEqual(task['last_error']['code'],'SINGLE_AGENT_REPAIR_LIMIT')
        self.assertFalse(task['report'].get('passed'))
        self.assertFalse(task['verification'][-1]['ok'])

    async def test_cancel_real_gui_wait_and_cleanup(self):
        self.gui['steps']=[{'tool':'desktop_wait','arguments':{'selector':{'automation_id':'Absent'},'state':'visible','seconds':30}}]
        await self.start([ProviderChunk(content='Run independent GUI',done=True)],wait=False)
        deadline=asyncio.get_running_loop().time()+60
        while not any(e['type']=='verification.progress' and e['payload']['stage']=='desktop_wait' and e['payload']['state']=='running' for e in self.client.messages):
            if asyncio.get_running_loop().time()>deadline: self.fail('Actual wait never started')
            await asyncio.sleep(.05)
        task=self.server.store.task_runtime.list(self.thread.id)[0]
        await self.server.tasks.handle(self.client,{'type':'task.cancel','thread_id':self.thread.id,'payload':{'task_id':task['id']}},set())
        self.assertEqual(self.server.store.task_runtime.get(task['id'])['status'],'cancelled')
        self.assertFalse(alive(json.loads(self.state.read_text(encoding='utf-8-sig'))['pid']))

    def configure_observer(self):
        from agent.core.model_catalog import KEY
        self.server.store.set_setting(KEY,json.dumps({'connections':[{'connection_id':'visual','display_name':'Fixture visual observer','provider_type':'openai_compatible','base_url':'https://unused.example.test/v1','credential_reference':'connection-visual','enabled':True}], 'profiles':[{'model_profile_id':'observer','connection_id':'visual','model_id':'fixture-vision','display_name':'Fixture','context_window':262144,'max_output_tokens':1024,'temperature':0,'tool_mode':'native','pricing':None,'supports_vision':True}]}))
        self.gui['vision_profile_id']='observer'

    def repair(self):
        return tool('apply_patch',path='app.ps1',old_text='Entry.Enabled=false;Status.Text="Settings broken"',new_text='Entry.Enabled=true;Status.Text="Settings ready"')

    async def test_separate_visual_observer_receives_actual_jpeg_only_as_observation(self):
        self.configure_observer()
        def observe(messages,model):
            import base64
            from io import BytesIO
            from PIL import Image
            parts=messages[-1]['content']
            raw=base64.b64decode(parts[1]['image_url']['url'].split(',')[1])
            self.assertTrue(raw.startswith(b'\xff\xd8'))
            self.assertIn('untrusted',messages[0]['content'])
            if model.seen and any('BackColor=Color.Blue' in str(m) for m in model.seen):
                with Image.open(BytesIO(raw)) as image:
                    blue=sum(b>160 and r<100 and g<120 for r,g,b in image.convert('RGB').get_flattened_data())
                    self.assertGreater(blue,500,'Final screenshot must actually contain the repaired blue button')
            return ProviderChunk(content='{"observations":["Settings visible"],"errors":[]}',done=True)
        def observe_error(messages,model):
            observe(messages,model)
            return ProviderChunk(content='{"observations":["Settings visible"],"errors":["Settings button needs blue background"]}',done=True)
        def fix_visual(messages,model):
            self.assertIn('Settings button needs blue background',str(messages))
            return tool('apply_patch',path='app.ps1',old_text='Text="Settings",Location=',new_text='Text="Settings",BackColor=Color.Blue,ForeColor=Color.White,Location=')
        task=await self.start([self.repair(),ProviderChunk(content='Verify with UIA and observer',done=True),observe_error,
                               fix_visual,ProviderChunk(content='Visual feedback repaired; recheck actual app',done=True),observe])
        self.assertEqual(task['status'],'awaiting_approval',task['reason'])
        self.assertEqual(task['attempts'],2)
        self.assertIn('BackColor=Color.Blue',task['report']['diff'])
        self.assertTrue(any(c['role']=='vision-observer' for c in self.server.store.task_runtime.calls(task['id'])))
        self.assertTrue(any(e['tool']=='vision_observer' for e in task['verification'][-1]['evidence']))

    async def test_upload_denial_never_calls_observer(self):
        self.configure_observer()
        class DenyUpload(Client):
            async def send_json(inner,event):
                inner.messages.append(event)
                if event['type']=='approval.requested':
                    deny=event['payload'].get('tool')=='desktop_screenshot' and event['payload'].get('arguments',{}).get('share_with_model')
                    inner.server.approvals.respond(event['payload']['approval_id'],'deny' if deny else 'allow_once')
        client=DenyUpload(self.server)
        task=await self.start([self.repair(),ProviderChunk(content='Verify',done=True)],client=client)
        self.assertEqual(task['status'],'paused',task['reason'])
        self.assertEqual(task['verification'][-1]['error_code'],'APPROVAL_DENIED')
        self.assertFalse(any(c['role']=='vision-observer' for c in self.server.store.task_runtime.calls(task['id'])))
