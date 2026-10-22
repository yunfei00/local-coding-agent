"""Single Agent project E2E: mock only model choices, execute every tool for real."""
import asyncio
import copy
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from agent.llm.base import ProviderChunk, ToolCall, ProviderError
from agent.llm.router import validate_config
from agent.server.main import AgentServer
from test_m2_processes import alive, wait_file

ROOT = Path(__file__).resolve().parents[1]


def tool(name, **args):
    return ProviderChunk(tool_calls=(ToolCall(name, args),), done=True, finish_reason='tool_calls')


def command(text):
    return tool('run_command', command=text, timeout_seconds=240)


def last_result(messages, name=None):
    for m in reversed(messages):
        if m['role'] == 'tool' and (name is None or m.get('name') == name):
            return json.loads(m['content'])
    raise AssertionError(f'Missing actual tool result {name}')


def process_id(messages):
    return last_result(messages, 'start_process')['data']['process_id']


def poll_ready(messages, provider):
    previous = last_result(messages)
    assert previous['ok'], previous.get('summary')
    if 'READY' not in previous.get('stdout', ''):
        provider.steps.insert(0, poll_ready)
        return tool('read_process', process_id=process_id(messages), cursor=previous.get('data', {}).get('next_cursor', 0), wait_seconds=5)
    # Readiness came from real process stdout; continue the next model choice.
    return provider.next(messages)


class ModelResponses:
    provider_name = 'scripted-model'
    preferred_model = 'single-executor'
    context_window = 262144
    def __init__(self, steps):
        self.steps, self.seen = list(steps), []
        self.blocked = asyncio.Event()
        self.release = asyncio.Event()
    def next(self, messages):
        if not self.steps:
            raise AssertionError('Model requested more responses than scripted')
        step = self.steps.pop(0)
        return step(messages, self) if callable(step) else step
    async def stream_chat(self, *, model, messages, tools=None):
        self.seen.append(copy.deepcopy(messages))
        choice = self.next(messages)
        if choice == 'block':
            self.blocked.set()
            await self.release.wait()
            choice = ProviderChunk(content='Released',done=True)
        yield choice


class Client:
    def __init__(self, server):
        self.server, self.messages = server, []
    async def send_json(self, event):
        self.messages.append(event)
        if event['type'] == 'approval.requested':
            self.server.approvals.respond(event['payload']['approval_id'], 'allow_once')


class EngineeringTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='m2-project-')
        self.root = Path(self.temp.name)
        self.env = patch.dict(os.environ, {'LCA_DATA_DIR': str(self.root / 'data'), 'LCA_M2_PYTHON': sys.executable, 'LCA_OPENAI_API_KEY': ''})
        self.env.start()
        self.server = AgentServer('fixture')
        self.server.permissions.set_mode('full_access')
        self.server.max_model_steps = 32
        self.client = Client(self.server)

    async def asyncTearDown(self):
        for running in list(self.server.active_turns.values()):
            running.cancel()
        await asyncio.gather(*list(self.server.active_turns.values()), return_exceptions=True)
        if hasattr(self, 'thread'):
            tasks = self.server.store.task_runtime.list(self.thread.id)
            if tasks:
                task = tasks[0]
                outputs = [{"name":e['payload']['name'], "result":e['payload']['result']} for e in self.client.messages if e['type']=='tool.completed']
                report = {'test':self.id(), 'task_status':task['status'], 'last_error':task.get('last_error'),
                          'verification':task['verification'], 'diff':task.get('report',{}).get('diff'),
                          'executions':self.server.store.task_plans.executions(task['id']), 'tool_results':outputs,
                          'scope_cleanup_events':[e['payload'] for e in self.client.messages if e['type']=='process.cleanup']}
                directory = ROOT/'validation-reports'
                directory.mkdir(exist_ok=True)
                (directory/('m2-project-'+self._testMethodName+'.json')).write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
        await self.server.close_async()
        self.server.close()
        self.env.stop()
        self.temp.cleanup()

    def repo(self, fixture):
        self.source = self.root / 'repo'
        shutil.copytree(ROOT / 'manual-fixtures' / fixture, self.source, ignore=shutil.ignore_patterns('node_modules', '__pycache__', 'runtime', 'lib', 'dist'))
        for args in (['init','-q','-b','main'], ['config','user.name','M2 test'], ['config','user.email','m2@example.test'], ['add','.'], ['commit','-qm','fixture']):
            subprocess.run(['git', *args], cwd=self.source, check=True, capture_output=True)
        self.project, self.thread, _ = self.server.projects.open(self.source, active_model='single-executor')

    async def start(self, steps, verification, wait=True):
        self.model = ModelResponses(steps)
        self.server.tasks.provider_factory_override = lambda *_: self.model
        config = validate_config({'strategy':'single-agent', 'roles':{'executor':{'model':'single-executor','context_window':262144,'output_limit':4096}},
            'budget':{'api_calls':50,'api_tokens':3000000,'global_api_calls':100,'global_api_tokens':9000000}, 'verification_commands':verification})
        await self.server.tasks.handle(self.client, {'type':'task.settings.update','payload':{'config':config}}, set())
        await self.server.tasks.handle(self.client, {'type':'task.start','thread_id':self.thread.id,
            'payload':{'goal':'Inspect the actual project, repair code, run tests/build, start and stop the application, inspect Diff. Keep tests unchanged.', 'config':config}}, set())
        running = list(self.server.active_turns.values())
        self.assertTrue(running, self.client.messages[-1])
        if wait:
            await asyncio.wait_for(asyncio.gather(*running), 360)
        return self.server.store.task_runtime.list(self.thread.id)[0]

    def results(self, name):
        return [e['payload']['result'] for e in self.client.messages if e['type'] == 'tool.completed' and e['payload']['name'] == name]

    def assert_verified(self, task):
        self.assertEqual(task['status'], 'awaiting_approval', task['reason'])
        self.assertTrue(all(v['ok'] for v in task['verification']))
        self.assertEqual(task.get('planning_attempts',0), 0)
        self.assertEqual(subprocess.check_output(['git','status','--porcelain'],cwd=self.source,text=True), '')
        self.assertTrue(any(c['role']=='executor' for c in self.server.store.task_runtime.calls(task['id'])))
        self.assertTrue(task['report']['diff'])

    async def test_python_actual_failure_feedback_patch_unittest_diff(self):
        self.repo('v04-local-first')
        cmd = 'uv run --no-project python -m unittest discover -s tests -v'
        task = await self.start([tool('read_file',path='calculator.py'), command(cmd),
            tool('apply_patch',path='calculator.py',old_text='return a - b',new_text='return a + b  # M2 repair'),
            command(cmd), tool('git_diff'), ProviderChunk(content='Actual tests and diff verified',done=True)], [cmd,'git diff --check'])
        self.assert_verified(task)
        results = self.results('run_command')
        self.assertNotEqual(results[0]['exit_code'],0)
        self.assertEqual(results[1]['exit_code'],0)
        self.assertIn('FAILED', str(self.model.seen[2]))
        self.assertTrue(Path(results[0]['data']['log_path']).exists())
        diagnostic = self.server.tasks.diagnostics(task['id'])['diagnostics']['json']
        self.assertTrue(any(e['metadata'].get('log_path') for e in diagnostic['executions']))

    async def test_react_typescript_multiround_repair_build_server_and_stop(self):
        self.repo('m2-react-ts')
        task = await self.start([
            command('npm ci --no-audit --no-fund'), tool('read_file',path='src/App.tsx'), command('npm run typecheck'),
            tool('apply_patch',path='src/App.tsx',old_text='const label: string = 123;',new_text='const label: string = "Calculator";'),
            command('npm test'), tool('read_file',path='src/math.ts'),
            tool('apply_patch',path='src/math.ts',old_text='return a - b;',new_text='return a + b;'),
            command('npm test'), command('npm run build'), tool('start_process',command='npm run dev',timeout_seconds=120),
            poll_ready, command('npm run probe'),
            lambda messages, _: tool('stop_process',process_id=process_id(messages)), tool('git_diff'),
            ProviderChunk(content='Real typecheck/tests/build and HTTP probe passed; server stopped',done=True)],
            ['npm test','npm run build','git diff --check'])
        self.assert_verified(task)
        workspace = Path(task['workspace'])
        data = json.loads((workspace/'runtime/server.json').read_text())
        self.assertFalse(alive(data['pid']), 'Leaked Vite/node process')
        from urllib.parse import urlsplit
        port = urlsplit(data['url']).port
        with self.assertRaises(OSError):
            await asyncio.open_connection('127.0.0.1',port)
        commands = self.results('run_command')
        self.assertTrue(any('TS2322' in r.get('stdout','') + r.get('stderr','') for r in commands))
        self.assertTrue(any('M2_HTTP_OK' in r.get('stdout','') for r in commands))
        self.assertGreaterEqual(sum(r['exit_code'] != 0 for r in commands),2)
        self.assertIn('TS2322', str(self.model.seen[3]))
        self.assertTrue((workspace/'dist/index.html').exists())
        self.assertEqual(subprocess.check_output(['git','diff','--','test'],cwd=workspace,text=True),'')
        self.assertTrue(all(not alive(r['data']['pid']) for r in self.results('start_process')))

    async def test_electron_real_main_node_python_descendants_stop_and_cancel(self):
        self.repo('m2-electron')
        task = await self.start([command('npm ci --no-audit --no-fund'), tool('read_file',path='math.cjs'), command('npm test'),
            tool('apply_patch',path='math.cjs',old_text='a - b',new_text='a + b'), command('npm test'),
            tool('start_process',command='npm start',timeout_seconds=120), poll_ready,
            lambda messages, _: tool('stop_process',process_id=process_id(messages)), tool('git_diff'),
            ProviderChunk(content='Actual Electron application started and tree stopped',done=True)], ['npm test','git diff --check'])
        self.assert_verified(task)
        workspace = Path(task['workspace'])
        actual = json.loads((workspace/'runtime/electron.json').read_text())
        self.assertTrue(actual['electron'])
        self.assertEqual(actual['type'],'browser')
        self.assertFalse(any(alive(actual[k]) for k in ('pid','node','python')), actual)
        # Cancel through the actual Task API while the model is waiting and the
        # real Electron app plus node/python descendants are still running.
        (workspace/'runtime/electron.json').unlink()
        self.model = ModelResponses([tool('start_process',command='npm start',timeout_seconds=120),poll_ready,'block'])
        self.server.tasks.provider_factory_override = lambda *_: self.model
        await self.server.tasks.handle(self.client, {'type':'task.resume','thread_id':self.thread.id,
            'payload':{'task_id':task['id'],'confirm_workspace':True}}, set())
        await asyncio.wait_for(self.model.blocked.wait(),30)
        actual = await wait_file(workspace/'runtime/electron.json')
        self.assertTrue(all(alive(actual[k]) for k in ('pid','node','python')))
        await self.server.tasks.handle(self.client, {'type':'task.cancel','thread_id':self.thread.id,'payload':{'task_id':task['id']}},set())
        self.assertEqual(self.server.store.task_runtime.get(task['id'])['status'],'cancelled')
        self.assertFalse(any(alive(actual[k]) for k in ('pid','node','python')), actual)
        journal = self.server.store.task_plans.executions(task['id'])
        self.assertEqual(sum(e['tool']=='start_process' for e in journal),2)
        self.assertTrue(all(e['metadata'].get('process_id') for e in journal if e['tool']=='start_process'))
        # Use the installed, repaired worktree for actual Electron cancellation,
        # timeout, root-exit cleanup and model-error cleanup. No global PID kills.
        await self._electron_cleanup_scenarios(workspace)

    async def _electron_cleanup_scenarios(self, workspace):
        from agent.tools.registry import ToolRegistry
        from agent.tools.workspace import Workspace
        tools = ToolRegistry(Workspace(workspace))
        pids_file = workspace/'runtime/electron.json'
        try:
            for mode in ('cancel','timeout','scope'):
                pids_file.unlink(missing_ok=True)
                started = await tools.execute('start_process', {'command':'npm start','timeout_seconds':4 if mode=='timeout' else 120},owner_id=mode)
                actual = await wait_file(pids_file)
                self.assertTrue(all(alive(actual[k]) for k in ('pid','node','python')))
                if mode=='timeout':
                    await asyncio.wait_for(asyncio.shield(tools.processes.get(started.data['process_id'],mode).task),15)
                else:
                    await tools.processes.close_owner(mode)
                self.assertFalse(any(alive(actual[k]) for k in ('pid','node','python')), (mode,actual))
        finally:
            await tools.processes.close()

    async def test_model_failure_after_background_start_cleans_turn_scope(self):
        self.repo('v04-local-first')
        def fail_after_started(messages, _):
            self.assertTrue(last_result(messages)['data']['process_id'])
            raise ProviderError('TEST_MODEL_ERROR','Deliberate model-only failure')
        task = await self.start([tool('start_process',command='uv run --no-project python -m http.server 0 --bind 127.0.0.1',timeout_seconds=120), fail_after_started], ['git diff --check'])
        self.assertEqual(task['status'],'paused')
        self.assertEqual(task['last_error']['code'],'TEST_MODEL_ERROR')
        started = self.results('start_process')[0]
        self.assertFalse(alive(started['data']['pid']))
        self.assertTrue(any(e['type']=='process.cleanup' for e in self.client.messages))

    async def test_normal_model_finish_cleans_unstopped_background(self):
        self.repo('v04-local-first')
        task = await self.start([tool('read_file',path='calculator.py'),
            tool('start_process',command='uv run --no-project python -m http.server 0 --bind 127.0.0.1',timeout_seconds=120),
            ProviderChunk(content='End process lifecycle check',done=True)],['git diff --check'])
        self.assertEqual(task['status'],'awaiting_approval',task['reason'])
        self.assertFalse(alive(self.results('start_process')[0]['data']['pid']))
        self.assertTrue(any(e['type']=='process.cleanup' for e in self.client.messages))
