"""Real shells, real process trees and sockets; no mocked process results."""
import asyncio
import ctypes
import json
import os
from pathlib import Path
import sys
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from agent.tools.base import ToolError
from agent.tools.registry import ToolRegistry
from agent.tools.workspace import Workspace


def alive(pid):
    if os.name == 'nt':
        from ctypes import wintypes
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel.OpenProcess.restype = wintypes.HANDLE
        kernel.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        handle = kernel.OpenProcess(0x1000, False, pid)
        if not handle:
            return False
        try:
            code = wintypes.DWORD()
            return bool(kernel.GetExitCodeProcess(handle, ctypes.byref(code)) and code.value == 259)
        finally:
            kernel.CloseHandle(handle)
    try:
        state = Path(f'/proc/{pid}/stat')
        if state.exists() and state.read_text().split(') ')[1].startswith('Z'):
            return False
        os.kill(pid, 0)
        return True
    except (ProcessLookupError, FileNotFoundError):
        return False


async def wait_file(path):
    # Cold Electron/WinForms startup under memory pressure can exceed 10s.
    # Still require the actual process marker; no simulated readiness.
    deadline=asyncio.get_running_loop().time()+30
    while asyncio.get_running_loop().time()<deadline:
        if path.exists():
            return json.loads(path.read_text())
        await asyncio.sleep(.05)
    raise AssertionError(f'Real process did not create readiness file: {path}')


class ProcessTests(unittest.IsolatedAsyncioTestCase):
    async def test_stop_cleanup_failure_keeps_specific_error_and_read_cannot_claim_success(self):
        started=await self.tools.execute('start_process',{'command':'node tree.cjs'},owner_id='cleanup-fault')
        session=self.tools.processes.get(started.data['process_id'],'cleanup-fault')
        await wait_file(self.root/'pids.json')
        original=session.job.terminate_and_wait
        async def fail_confirmation(*args,**kwargs):
            await original(*args,**kwargs)
            from agent.tools.processes import terminate_process_tree
            await terminate_process_tree(session.process)
            raise TimeoutError('injected exit confirmation fault')
        with patch.object(session.job,'terminate_and_wait',side_effect=fail_confirmation):
            with self.assertRaises(ToolError) as caught:
                await self.tools.execute('stop_process',{'process_id':session.id},owner_id='cleanup-fault')
        self.assertEqual(caught.exception.code,'PROCESS_CLEANUP_FAILED')
        self.assertIn('job_exit_confirmation',caught.exception.message)
        result=await self.tools.execute('read_process',{'process_id':session.id},owner_id='cleanup-fault')
        self.assertFalse(result.ok)
        self.assertEqual(result.data['error_code'],'PROCESS_CLEANUP_FAILED')
        # The injected diagnostic must not leave a failing future in teardown.
        self.tools.processes.sessions.pop(session.id)

    @unittest.skipUnless(os.name=='nt','Windows owned window shutdown')
    def test_graceful_close_never_messages_foreign_or_reused_pid_windows(self):
        from types import SimpleNamespace
        from agent.tools.windows_job import WindowsJob
        class Fn:
            def __init__(self,fn):self.fn=fn
            def __call__(self,*args):return self.fn(*args)
        posted=[]
        def pid(hwnd,out):out._obj.value={11:1,22:9,33:2,44:1}[hwnd];return 1
        def member(handle,job,out):out._obj.value=handle==101;return True
        user=SimpleNamespace(EnumWindows=Fn(lambda callback,param:[callback(h,param) for h in (11,22,33,44)]),
            GetWindowThreadProcessId=Fn(pid),IsWindowVisible=Fn(lambda h:h!=44),
            PostMessageW=Fn(lambda hwnd,*args:posted.append(hwnd) or True))
        job=WindowsJob.__new__(WindowsJob);job.handle=7
        job.kernel=SimpleNamespace(WaitForSingleObject=lambda h,wait:258,IsProcessInJob=member)
        with patch('agent.tools.windows_job.ctypes.WinDLL',return_value=user):
            self.assertEqual(job._close_owned_windows([(1,101),(2,102)]),1)
        self.assertEqual(posted,[11])

    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='m2 space 中文 ')
        self.root = Path(self.temp.name)
        self.env = patch.dict(os.environ, {'LCA_DATA_DIR': str(self.root / 'data'), 'LCA_M2_PYTHON': sys.executable})
        self.env.start()
        self.tools = ToolRegistry(Workspace(self.root))
        (self.root / 'child script.cjs').write_text("console.log('中文 output'); process.exit(Number(process.argv[2] || 0));", encoding='utf-8')
        (self.root / 'tree.cjs').write_text("""const {spawn}=require('node:child_process');
const fs=require('node:fs');
const child=spawn(process.env.LCA_M2_PYTHON,['-c','import time; time.sleep(120)'],{stdio:'inherit'});
fs.writeFileSync('pids.json',JSON.stringify({node:process.pid,python:child.pid}));
console.log('TREE_READY',process.pid,child.pid);
if(process.argv[2]==='exit') process.exit(0);
setInterval(()=>console.log('HEARTBEAT'),100);
""", encoding='utf-8')

    async def asyncTearDown(self):
        await self.tools.processes.close()
        self.env.stop()
        self.temp.cleanup()

    async def test_default_shell_space_unicode_and_real_exit_code(self):
        result = await self.tools.execute('run_command', {'command': 'node "child script.cjs" 7'})
        self.assertFalse(result.ok)
        self.assertEqual(result.exit_code, 7)
        self.assertIn('中文 output', result.stdout)
        self.assertTrue(Path(result.data['log_path']).is_file())
        self.assertFalse(alive(result.data['pid']))

    @unittest.skipUnless(os.name == 'nt', 'Windows CMD')
    async def test_cmd_quotes_space_unicode_and_exit_code(self):
        result = await self.tools.execute('run_command', {'command': 'node "child script.cjs" 9', 'shell': 'cmd'})
        self.assertEqual(result.exit_code, 9, result.stderr)
        self.assertIn('中文 output', result.stdout)

    async def test_background_read_stop_and_scope_ownership(self):
        result = await self.tools.execute('start_process', {'command': 'node tree.cjs', 'timeout_seconds': 120}, owner_id='a')
        ident = result.data['process_id']
        pids = await wait_file(self.root / 'pids.json')
        self.assertTrue(all(alive(pid) for pid in pids.values()))
        with self.assertRaises(ToolError):
            await self.tools.execute('stop_process', {'process_id': ident}, owner_id='b')
        read = await self.tools.execute('read_process', {'process_id': ident, 'wait_seconds': 1}, owner_id='a')
        self.assertIn('TREE_READY', read.stdout)
        cursor = read.data['next_cursor']
        next_read = await self.tools.execute('read_process', {'process_id': ident, 'cursor': cursor, 'wait_seconds': 2}, owner_id='a')
        self.assertGreater(next_read.data['next_cursor'], cursor)
        stopped = await self.tools.execute('stop_process', {'process_id': ident}, owner_id='a')
        self.assertEqual(stopped.data['state'], 'stopped')
        self.assertFalse(any(alive(pid) for pid in [*pids.values(), result.data['pid']]))
        metadata = json.loads(Path(stopped.data['metadata_path']).read_text(encoding='utf-8'))
        self.assertEqual(metadata['cleanup_reason'], 'user_stopped')

    async def test_normal_parent_exit_does_not_leave_python_descendant(self):
        result = await asyncio.wait_for(self.tools.execute('run_command', {'command': 'node tree.cjs exit'}), 15)
        pids = await wait_file(self.root / 'pids.json')
        self.assertTrue(result.ok, result.stderr)
        self.assertFalse(any(alive(pid) for pid in pids.values()))

    async def test_timeout_retains_output_and_cleans_tree(self):
        with self.assertRaises(ToolError) as caught:
            await self.tools.execute('run_command', {'command': 'node tree.cjs', 'timeout_seconds': 2})
        self.assertEqual(caught.exception.code, 'COMMAND_TIMEOUT')
        self.assertIn('TREE_READY', caught.exception.details['stdout'])
        pids = await wait_file(self.root / 'pids.json')
        self.assertFalse(any(alive(pid) for pid in pids.values()))

    async def test_foreground_cancel_cleans_node_and_python(self):
        task = asyncio.create_task(self.tools.execute('run_command', {'command': 'node tree.cjs'}))
        pids = await wait_file(self.root / 'pids.json')
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertFalse(any(alive(pid) for pid in pids.values()))

    async def test_git_hook_cancel_cleans_real_node_python_descendants(self):
        from agent.tools.git import _git
        subprocess.run(['git','init','-q'],cwd=self.root,check=True)
        hook = self.root/'.git/hooks/pre-commit'
        hook.write_text('#!/bin/sh\nexec node tree.cjs\n',encoding='utf-8')
        hook.chmod(0o755)
        task = asyncio.create_task(_git(Workspace(self.root),'-c','user.name=M2','-c','user.email=m2@example.test','commit','--allow-empty','-m','fixture'))
        pids = await wait_file(self.root/'pids.json')
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertFalse(any(alive(pid) for pid in pids.values()))

    async def test_scope_cleanup_stops_unstopped_background(self):
        result = await self.tools.execute('start_process', {'command': 'node tree.cjs', 'timeout_seconds': 1800}, owner_id='scope')
        pids = await wait_file(self.root / 'pids.json')
        cleanup = await self.tools.processes.close_owner('scope')
        self.assertEqual(cleanup[0]['process_id'], result.data['process_id'])
        self.assertFalse(any(alive(pid) for pid in pids.values()))

    async def test_background_timeout_stops_process_without_polling(self):
        # Keep the two-second process deadline. PowerShell cold startup alone
        # can exceed it on a memory-starved host; shell behavior has separate
        # real tests. CMD starts the same actual Node/Python tree here.
        result = await self.tools.execute('start_process', {'command': 'node tree.cjs', 'timeout_seconds': 2,
            'shell':'cmd' if os.name=='nt' else 'auto'})
        pids = await wait_file(self.root / 'pids.json')
        session = self.tools.processes.get(result.data['process_id'])
        await asyncio.wait_for(asyncio.shield(session.task), 10)
        self.assertEqual(session.state, 'timed_out')
        self.assertFalse(any(alive(pid) for pid in pids.values()))

    async def test_output_callback_failure_does_not_leak(self):
        async def disconnected(chunk):
            raise ConnectionResetError('test client disconnected')
        with self.assertRaises(ToolError) as caught:
            await self.tools.execute('run_command', {'command': 'node tree.cjs'}, on_output=disconnected)
        self.assertEqual(caught.exception.code, 'COMMAND_OUTPUT_FAILED')
        self.assertFalse(alive(caught.exception.details['data']['pid']))

    async def test_late_output_error_after_root_exit_is_not_success(self):
        async def late_disconnect(stream, text):
            session = next(iter(self.tools.processes.sessions.values()))
            while session.process.returncode is None:
                await asyncio.sleep(.02)
            raise ConnectionResetError('consumer closed after process exit')
        with self.assertRaises(ToolError) as caught:
            await self.tools.execute('run_command',{'command':'node "child script.cjs" 0'},on_raw_output=late_disconnect)
        self.assertEqual(caught.exception.code,'COMMAND_OUTPUT_FAILED')
        self.assertEqual(caught.exception.details['exit_code'],0)
        self.assertFalse(alive(caught.exception.details['data']['pid']))

    async def test_stop_with_stalled_output_consumer_still_cleans_tree_and_owner(self):
        receiving = asyncio.Event()
        async def stalled(stream, text):
            receiving.set()
            await asyncio.Event().wait()
        session = await self.tools.processes.launch({'command':'node tree.cjs'},owner='slow',on_raw_output=stalled)
        pids = await wait_file(self.root/'pids.json')
        await asyncio.wait_for(receiving.wait(),10)
        stopped = await asyncio.wait_for(self.tools.processes.stop(session.id,owner='slow'),15)
        self.assertEqual(stopped.data['state'],'stopped')
        self.assertTrue(stopped.data['output_drain_timed_out'])
        self.assertTrue(stopped.data['output_truncated'])
        self.assertFalse(any(alive(pid) for pid in [session.process.pid,*pids.values()]))
        if os.name=='nt':
            metadata=json.loads(Path(stopped.data['metadata_path']).read_text(encoding='utf-8'))
            self.assertTrue(metadata['job_cleanup']['confirmed_exit'])
            self.assertGreaterEqual(metadata['job_cleanup']['owned_process_count'],2)
        self.assertEqual(len(await self.tools.processes.close_owner('slow')),1)
        self.assertEqual(await self.tools.processes.close_owner('slow'),[])

    async def test_normal_exit_with_stalled_output_consumer_is_not_test_pass(self):
        async def stalled(stream, text):
            await asyncio.Event().wait()
        with self.assertRaises(ToolError) as caught:
            await self.tools.execute('run_command',{'command':'node "child script.cjs" 0'},on_raw_output=stalled)
        self.assertEqual(caught.exception.code,'COMMAND_OUTPUT_FAILED')
        self.assertTrue(caught.exception.details['data']['output_drain_timed_out'])
        self.assertFalse(alive(caught.exception.details['data']['pid']))
        from agent.core.verification import classify
        self.assertEqual(classify({'ok':False,'exit_code':0,'error':{'code':caught.exception.code}}),'environment',
                         'Incomplete output must pause as an environment issue rather than trigger paid code repair')

    @unittest.skipIf(os.name == 'nt', 'POSIX process group')
    async def test_sigterm_ignoring_descendant_is_killed_after_root_exit(self):
        (self.root/'stubborn.cjs').write_text("const {spawn}=require('node:child_process'); const fs=require('node:fs'); const p=spawn(process.env.LCA_M2_PYTHON,['-c',\"import signal,time,json,os; from pathlib import Path; signal.signal(signal.SIGTERM,signal.SIG_IGN); Path('ready.json').write_text(json.dumps({'pid':os.getpid()})); time.sleep(120)\"],{stdio:'inherit'}); setInterval(()=>{},1000);",encoding='utf-8')
        started = await self.tools.execute('start_process',{'command':'node stubborn.cjs'},owner_id='stubborn')
        data = await wait_file(self.root/'ready.json')
        await self.tools.processes.close_owner('stubborn')
        self.assertFalse(alive(data['pid']))
        self.assertFalse(alive(started.data['pid']))

    async def test_split_utf8_output_and_bounded_tail(self):
        (self.root / 'unicode.py').write_text("import sys,time\nb='中'.encode()\nsys.stdout.buffer.write(b[:1]);sys.stdout.flush();time.sleep(.05)\nsys.stdout.buffer.write(b[1:]);sys.stdout.flush()\nprint('x'*210000)\nprint('TAIL_MARKER')\n", encoding='utf-8')
        result = await self.tools.execute('run_command', {'command': 'uv run --no-project python unicode.py'})
        self.assertTrue(result.ok, result.stderr)
        self.assertLessEqual(len(result.stdout), 200000)
        self.assertIn('TAIL_MARKER', result.stdout)
        log = Path(result.data['log_path']).read_text(encoding='utf-8')
        self.assertIn('中', log)
        self.assertNotIn('�', log)
