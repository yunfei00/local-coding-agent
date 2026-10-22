import json
from pathlib import Path
import tempfile
import unittest
import os
from unittest.mock import patch

from agent.core.project_detection import detect_project
from agent.permissions.policy import PermissionPolicy
from agent.tools.workspace import Workspace


class ProjectPermissionTests(unittest.TestCase):
    def test_nested_npm_script_and_hook_require_approval(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            workspace = Workspace(root)
            policy = PermissionPolicy()
            for scripts in ({'test':'npm run cleanup','cleanup':'rm -rf sentinel'},
                            {'test':'node test.cjs','pretest':'del sentinel'},
                            {'dev':'npm publish'}):
                (root/'package.json').write_text(json.dumps({'scripts':scripts}))
                for name in ('run_command','start_process'):
                    verdict = policy.evaluate(tool_name=name, arguments={'command':'npm run ' + ('dev' if 'dev' in scripts else 'test')}, workspace=workspace)
                    self.assertTrue(verdict.requires_approval, (name,scripts))

    def test_new_tools_not_available_in_read_only_and_no_external_start(self):
        with tempfile.TemporaryDirectory() as temp:
            workspace = Workspace(temp)
            policy = PermissionPolicy('read_only')
            for name in ('start_process','read_process','stop_process'):
                self.assertFalse(policy.evaluate(tool_name=name,arguments={},workspace=workspace).allowed)
            policy.set_mode('workspace')
            self.assertFalse(policy.evaluate(tool_name='start_process',arguments={'command':'node dev.cjs','cwd':'..'},workspace=workspace).allowed)

    def test_detects_actual_fixtures_without_executing_scripts(self):
        fixtures = Path(__file__).resolve().parents[1]/'manual-fixtures'
        detection = detect_project(fixtures/'m2-react-ts')
        self.assertTrue({'node','react','typescript'}.issubset(detection.detected))
        self.assertIn('electron', detect_project(fixtures/'m2-electron').detected)
        self.assertTrue(any(s.purpose=='serve' and not s.safe for s in detection.suggestions))

    def test_npm_script_cycles_do_not_recurse_forever(self):
        with tempfile.TemporaryDirectory() as temp:
            (Path(temp)/'package.json').write_text(json.dumps({'scripts':{'test':'npm run loop','loop':'npm test'}}))
            verdict = PermissionPolicy().evaluate(tool_name='run_command',arguments={'command':'npm test'},workspace=Workspace(temp))
            self.assertTrue(verdict.allowed)


class ActualApprovalTests(unittest.IsolatedAsyncioTestCase):
    async def test_denied_destructive_npm_script_never_launches(self):
        from agent.server.main import AgentServer
        from agent.llm.base import ToolCall
        with tempfile.TemporaryDirectory() as temp, patch.dict(os.environ,{'LCA_DATA_DIR':str(Path(temp)/'data'),'LCA_OPENAI_API_KEY':''}):
            root = Path(temp)/'repo'
            root.mkdir()
            (root/'sentinel').write_text('keep')
            (root/'package.json').write_text(json.dumps({'scripts':{'bad':'rm -rf sentinel'}}))
            server = AgentServer('test')
            project, thread, _ = server.projects.open(root, active_model='test')
            approvals = []
            class Client:
                async def send_json(self, event):
                    if event['type']=='approval.requested':
                        approvals.append(event)
                        server.approvals.respond(event['payload']['approval_id'],'deny')
            try:
                result = await server._authorize_tool(Client(),project=project,call=ToolCall('start_process',{'command':'npm run bad'}),
                    call_id='test',thread_id=thread.id,turn_id='test',user_prompt='Inspect project')
                self.assertEqual(result['error']['code'],'APPROVAL_DENIED')
                self.assertEqual(len(approvals),1)
                self.assertEqual((root/'sentinel').read_text(),'keep')
                self.assertFalse(project.tools.processes.sessions)
            finally:
                await server.close_async()
                server.close()
