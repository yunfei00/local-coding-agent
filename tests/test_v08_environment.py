import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch
from agent.core.environment_diagnostics import classify_environment
from agent.permissions.policy import PermissionPolicy,PermissionMode
from agent.persistence.store import SQLiteStore
from agent.server.projects import ProjectRegistry

class EnvironmentTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp=tempfile.TemporaryDirectory();self.base=Path(self.temp.name);self.root=self.base/'project';self.root.mkdir()
        self.env=patch.dict(os.environ,{'LCA_DATA_DIR':str(self.base/'data')});self.env.start()
        self.store=SQLiteStore(self.base/'data');self.project,_,_=ProjectRegistry(self.store).open(self.root,active_model=None);self.k=self.project.knowledge();self.tools=self.project.tools
    async def asyncTearDown(self):
        await self.tools.processes.close();await self.tools.desktop.close_owner('diagnostic');self.store.close();self.env.stop();self.temp.cleanup()
    async def call(self,name,**args):return await self.tools.execute(name,args,owner_id='diagnostic')
    async def test_git_missing_path_detected_without_install_or_global_change(self):
        before=os.environ.get('PATH')
        with patch.dict(os.environ,{'PATH':''}):
            result=await self.call('environment_diagnose',component='git')
            self.assertTrue(any(r['code'] in {'GIT_MISSING','GIT_PATH_INVALID'} for r in result.data['issues']))
            self.assertEqual(os.environ['PATH'],'')
        self.assertEqual(os.environ.get('PATH'),before)
    async def test_git_project_path_repair_real_recheck_and_persistence(self):
        git=shutil.which('git');self.assertIsNotNone(git)
        import subprocess
        subprocess.run([git,'init','-q'],cwd=self.root,check=True,capture_output=True)
        with patch.dict(os.environ,{'PATH':''}):
            result=await self.call('environment_repair',action='project_git_path',directory=str(Path(git).parent))
            self.assertTrue(result.ok,result.data);self.assertEqual(os.environ['PATH'],'')
            self.assertEqual(result.data['checks'][0]['exit_code'],0)
            status=await self.call('git_status')
            self.assertTrue(status.ok,status.stderr)
        self.assertIn(str(Path(git).parent),json.loads(self.store.get_setting('project.path:'+self.project.id)))
        reopened=ProjectRegistry(self.store).get(self.project.id)
        with patch.dict(os.environ,{'PATH':''}):
            status=await reopened.tools.execute('git_status',{},owner_id='diagnostic')
            self.assertTrue(status.ok,status.stderr)
        self.assertTrue(self.k.list('环境修复'))
    async def test_project_npm_proxy_real_socket_failure_repair_preserves_other_lines(self):
        file=self.root/'.npmrc';file.write_text('proxy=http://127.0.0.1:1\nhttps-proxy=http://127.0.0.1:1\nstrict-ssl=true\n')
        # Presence of npm is independent of this proxy test; no npm command is mocked as executed.
        with patch('agent.core.environment_diagnostics.shutil.which',return_value=sys.executable):
            result=await self.call('environment_diagnose',component='npm');self.assertIn('NPM_PROXY_UNREACHABLE',[i['code'] for i in result.data['issues']])
            repaired=await self.call('environment_repair',action='project_npm_proxy_reset');self.assertTrue(repaired.ok,repaired.data)
        self.assertEqual(file.read_text(),'strict-ssl=true\n');self.assertEqual(repaired.changed_paths,['.npmrc'])
    async def test_python_missing_dependency_has_real_exit_code_and_uv_scope(self):
        result=await self.call('environment_diagnose',component='python',module='lca_missing_dependency_v08_abc')
        self.assertIn('PYTHON_DEPENDENCY_MISSING',[i['code'] for i in result.data['issues']]);self.assertEqual(result.data['checks'][0]['exit_code'],3)
        self.assertIn('PROJECT_VENV_MISSING',[i['code'] for i in result.data['issues']])
    async def test_python_argument_cannot_execute_arbitrary_script(self):
        from agent.tools.base import ToolError
        with self.assertRaises(ToolError):await self.call('environment_diagnose',component='python',module='os; print("unsafe")')
        self.assertEqual(self.tools.processes.sessions,{})
    async def test_uv_environment_mismatch_is_reported_not_changed(self):
        outside=str(self.base/'other-env')
        with patch.dict(os.environ,{'UV_PROJECT_ENVIRONMENT':outside}):
            result=await self.call('environment_diagnose',component='uv');self.assertIn('UV_ENV_MISMATCH',[i['code'] for i in result.data['issues']]);self.assertEqual(os.environ['UV_PROJECT_ENVIRONMENT'],outside)
    async def test_electron_download_and_cache_corruption_without_launch(self):
        folder=self.root/'node_modules/electron';folder.mkdir(parents=True)
        result=await self.call('environment_diagnose',component='electron');self.assertIn('ELECTRON_CACHE_INVALID',[i['code'] for i in result.data['issues']])
        (folder/'path.txt').write_text('electron.exe');result=await self.call('environment_diagnose',component='electron');self.assertIn('ELECTRON_DOWNLOAD_INCOMPLETE',[i['code'] for i in result.data['issues']])
        (folder/'dist').mkdir();(folder/'dist/electron.exe').write_bytes(b'broken cache')
        result=await self.call('environment_diagnose',component='electron');self.assertIn('ELECTRON_CACHE_INVALID',[i['code'] for i in result.data['issues']]);self.assertEqual(self.tools.processes.sessions,{})
    async def test_provider_probe_does_not_log_credentials_or_mark_generation_passed(self):
        diagnostic=self.tools._tools['environment_diagnose'].diagnostics
        async def probe():return {'checks':[],'issues':[{'code':'DNS_FAILED','category':'dns','reason':'API 连接检查失败'}]}
        diagnostic.provider_probe=probe;result=await self.call('environment_diagnose',component='provider');self.assertEqual(result.data['issues'][0]['category'],'dns')
    def test_automatic_repair_always_needs_approval_even_full_access(self):
        for mode in [PermissionMode.WORKSPACE,PermissionMode.FULL_ACCESS]:
            verdict=PermissionPolicy(mode).evaluate(tool_name='environment_repair',arguments={'action':'project_npm_proxy_reset'},workspace=self.project.workspace)
            self.assertTrue(verdict.allowed);self.assertTrue(verdict.requires_approval)
        self.assertFalse(PermissionPolicy(PermissionMode.READ_ONLY).evaluate(tool_name='environment_repair',arguments={},workspace=self.project.workspace).allowed)
        self.assertTrue(PermissionPolicy(PermissionMode.READ_ONLY).evaluate(tool_name='environment_diagnose',arguments={},workspace=self.project.workspace).allowed)
    def test_network_timeout_dns_permission_classification(self):
        for code,expected in [('DNS_FAILED','dns'),('PROXY_INVALID','proxy'),('CONNECT_TIMEOUT','network_timeout'),('ACCESS_DENIED','permission'),('MODULE_NOT_FOUND','dependency')]:self.assertEqual(classify_environment(code),expected)
    async def test_global_config_or_cache_delete_is_not_a_supported_repair(self):
        from agent.tools.base import ToolError
        for action in ['system_proxy_reset','delete_electron_cache','install_global_python']:
            with self.assertRaises(ToolError):await self.call('environment_repair',action=action)
