import json
from pathlib import Path
import tempfile
import sys
import unittest
from unittest.mock import AsyncMock, patch

from agent.core.workflow_delivery import build_delivery,write_delivery
from agent.tools.git import GitCIStatusTool
from agent.tools.workspace import Workspace
from agent.tools.base import ToolResult,ToolError
from agent.tools.processes import ProcessManager
from agent.llm.openai_compatible import OpenAICompatibleProvider


class DeliveryTests(unittest.TestCase):
    def test_report_cannot_claim_tests_passed_without_exit_code(self):
        for tests in ([],[{'ok':True,'exit_code':None}],[{'ok':False,'exit_code':1}]):
            report,markdown=build_delivery('goal',{'verification':tests},None,[],[])
            self.assertNotEqual(report['status'],'已完成且验证通过')
        report,_=build_delivery('goal',{'verification':[{'ok':True,'exit_code':0}]},{'steps':[{'id':'a','description':'x','state':'blocked'}]},[],[])
        self.assertTrue(report['unfinished'])
        self.assertNotEqual(report['status'],'已完成且验证通过')

    def test_report_atomic_artifacts_redact_keys(self):
        with tempfile.TemporaryDirectory() as folder:
            paths=write_delivery(folder,'run',{'goal':'secret-example'},'secret-example',exact_secrets=['secret-example'])
            self.assertNotIn('secret-example',Path(paths['md_path']).read_text(encoding='utf-8'))
            self.assertNotIn('secret-example',json.loads(Path(paths['json_path']).read_text(encoding='utf-8'))['goal'])
            self.assertFalse(list(Path(folder).glob('*.tmp')))

    def test_large_report_stays_valid_json_and_keeps_structured_evidence(self):
        with tempfile.TemporaryDirectory() as folder:
            report={'calls':[{'request_id':str(i),'summary':'x'*2000} for i in range(150)]}
            result=write_delivery(folder,'large',report,'report')
            parsed=json.loads(Path(result['json_path']).read_text(encoding='utf-8'))
            self.assertEqual(len(parsed['calls']),150)

    def test_remote_error_keeps_only_protocol_identifiers(self):
        provider=OpenAICompatibleProvider(base_url='https://example.test/v1',api_key='not-used')
        exc=provider._http_error(400,{'error':{'code':'invalid_parameter','param':'max_tokens','type':'bad_request','message':'API Key private; full sensitive prompt'}},'failed')
        self.assertEqual(exc.remote_error['param'],'max_tokens')
        self.assertNotIn('private',str(exc));self.assertNotIn('message',exc.remote_error)


class CIToolTests(unittest.IsolatedAsyncioTestCase):
    async def test_private_cli_capture_cannot_write_credentials_to_output_log(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);logs=root/'logs'
            manager=ProcessManager(Workspace(root),log_root=logs,persist_output=False)
            try:
                result=await manager.run({'command':'private-inspection','timeout_seconds':10},argv=[sys.executable,'-c',"print('synthetic-sensitive-marker')"])
                self.assertIn('synthetic-sensitive-marker',result.stdout)
                self.assertIsNone(result.data['log_path'])
                self.assertFalse(any('synthetic-sensitive-marker' in p.read_text(encoding='utf-8') for p in logs.rglob('*') if p.is_file()))
            finally:await manager.close()
    async def test_ci_read_is_commit_scoped_and_never_mutates(self):
        with tempfile.TemporaryDirectory() as folder:
            sha='a'*40
            result=ToolResult(ok=True,summary='ok',stdout=json.dumps([{'headSha':sha,'status':'completed','conclusion':'success'}]),exit_code=0)
            with patch('agent.tools.git._git',AsyncMock(side_effect=[(0,'https://github.com/owner/repo.git',''),(0,sha,'')])),patch('agent.tools.git.ProcessManager') as manager:
                manager.return_value.run=AsyncMock(return_value=result);manager.return_value.close=AsyncMock()
                out=await GitCIStatusTool(Workspace(Path(folder))).execute({})
                self.assertTrue(out.data['all_returned_runs_passed'])
                args=manager.return_value.run.call_args.kwargs['argv']
                self.assertEqual(args[:3],['gh','run','list']);self.assertIn(sha,args)
                self.assertNotIn('push',args);manager.return_value.close.assert_awaited_once()

    async def test_untrusted_origin_and_sha_reject_before_network(self):
        with tempfile.TemporaryDirectory() as folder:
            with patch('agent.tools.git._git',AsyncMock(return_value=(0,'https://evil.test/owner/repo.git',''))):
                with self.assertRaises(ToolError):await GitCIStatusTool(Workspace(Path(folder))).execute({})


if __name__=='__main__':unittest.main()
