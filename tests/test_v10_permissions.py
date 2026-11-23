import json
import unittest
from pathlib import Path
from unittest.mock import AsyncMock,patch

import test_unified_runtime as fixture
from agent.permissions.authorization import AuthorizationSettings
from agent.permissions.policy import PermissionMode
from agent.llm.base import ToolCall
from agent.core.execution import ExecutionBudget


class AuthorizationTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp=fixture.UnifiedLoopTests.asyncSetUp
    asyncTearDown=fixture.UnifiedLoopTests.asyncTearDown

    def grant(self,mode='full_access',**kwargs):
        return self.server.authorizations.configure(mode,**kwargs)

    async def call(self,name,args):
        return await self.server._authorize_tool(self.ws,project=self.project,call=ToolCall(name,args),call_id='v10:'+name,
            thread_id=self.thread.id,turn_id='v10',user_prompt='完成隔离工程开发，不要推送')

    def test_full_access_selection_is_consent_and_restart_restores_it(self):
        self.grant()
        restored=AuthorizationSettings(self.server.store)
        self.assertTrue(restored.effective(self.project.id).continuous)
        self.grant('workspace');self.grant()
        self.assertTrue(restored.effective().continuous)

    def test_legacy_full_access_is_not_silently_expanded(self):
        self.server.store.set_setting('permission_mode','full_access')
        self.assertEqual(self.server.authorizations.load()['global'],'workspace')
        self.assertFalse(self.server.authorizations.effective().continuous)

    def test_scopes_priorities_and_inheritance_are_persistent(self):
        self.grant('read_only');self.grant('workspace',scope='project',target=self.project.id)
        self.grant(scope='task',target='isolated-task',confirmed=True)
        restored=AuthorizationSettings(self.server.store)
        self.assertTrue(restored.effective(self.project.id,'isolated-task').continuous)
        self.assertEqual(restored.effective(self.project.id,'other-task').mode,PermissionMode.WORKSPACE)
        self.assertEqual(restored.effective('other-project').mode,PermissionMode.READ_ONLY)
        self.grant('inherit',scope='task',target='isolated-task')
        self.assertEqual(restored.effective(self.project.id,'isolated-task').mode,PermissionMode.WORKSPACE)

    async def test_read_only_refuses_actual_write(self):
        self.grant('read_only')
        r=await self.call('write_file',{'path':'denied.txt','content':'x'})
        self.assertFalse(r['ok']);self.assertFalse((self.repo/'denied.txt').exists())

    async def test_workspace_external_file_requires_approval_and_does_not_keep_grant(self):
        self.grant('workspace');outside=self.root/'outside.txt'
        self.server.approvals.request=AsyncMock(return_value='deny')
        r=await self.call('write_file',{'path':str(outside),'content':'x'})
        self.assertFalse(r['ok']);self.assertFalse(outside.exists())
        self.server.approvals.request=AsyncMock(return_value='allow_once')
        r=await self.call('write_file',{'path':str(outside),'content':'authorized'})
        self.assertTrue(r['ok']);self.assertEqual(outside.read_text(),'authorized')
        self.assertFalse(self.project.workspace.allow_outside)

    async def test_full_access_files_shell_delete_without_repeated_approvals(self):
        self.grant(confirmed=True)
        self.server.approvals.request=AsyncMock(side_effect=AssertionError('ordinary operation requested approval'))
        self.assertTrue((await self.call('write_file',{'path':'normal.txt','content':'hello'}))['ok'])
        self.assertTrue((await self.call('run_command',{'command':'uv run --no-project python -c "print(123)"'}))['ok'])
        result=await self.call('delete_file',{'path':'normal.txt'})
        self.assertTrue(result['ok']);self.assertFalse((self.repo/'normal.txt').exists())
        recovery=self.server.store.path.parent/'file-recovery'/(result['data']['recovery_id']+'.bin')
        self.assertEqual(recovery.read_text(),'hello')
        audit=self.server.store.connection.execute('SELECT COUNT(*) FROM permission_audit WHERE decision="allow"').fetchone()[0]
        self.assertEqual(audit,3)

    async def test_revocation_immediately_blocks_next_operation(self):
        self.grant(confirmed=True)
        self.assertTrue((await self.call('write_file',{'path':'first.txt','content':'x'}))['ok'])
        self.grant('read_only')
        self.assertFalse((await self.call('write_file',{'path':'second.txt','content':'x'}))['ok'])
        self.assertFalse((self.repo/'second.txt').exists())

    async def test_task_grant_survives_plan_rebind_and_current_toolbar_can_revoke(self):
        execution=ExecutionBudget(self.server.store.connection,'scoped-turn',self.thread.id,self.server.continuation_policy)
        execution.data['permission_task_key']='scoped-turn';execution.data['unified']={'phase':'executing'};execution.save()
        self.grant(scope='task',target='scoped-turn',confirmed=True)
        execution.bind_plan('scoped-plan')
        self.server.active_executions['scoped-turn']=execution;self.server.active_turn_threads['scoped-turn']=self.thread.id
        self.assertTrue(self.server._permission_policy(self.project,execution).continuous)
        await self.server.handle_message(self.ws,{'type':'permission.set','payload':{'mode':'read_only','scope':'current'}},set())
        self.assertEqual(self.ws.messages[-1]['type'],'permission.changed')
        self.assertEqual(self.ws.messages[-1]['payload']['mode'],'read_only')
        self.assertEqual(self.server._permission_policy(self.project,execution).mode,PermissionMode.READ_ONLY)
        self.assertEqual(self.server.authorizations.effective(self.project.id,'new-task').mode,PermissionMode.WORKSPACE)

    async def test_full_access_does_not_delete_frozen_acceptance_files(self):
        from agent.core.verification import acceptance_snapshot
        self.grant(confirmed=True);before=(self.repo/'tests/test_calc.py').read_bytes()
        execution=ExecutionBudget(self.server.store.connection,'protected',self.thread.id,self.server.continuation_policy)
        execution.data['workflow_acceptance_baseline']=acceptance_snapshot(self.repo)
        self.server.active_executions['v10']=execution
        result=await self.call('delete_file',{'path':'tests/test_calc.py'})
        self.assertFalse(result['ok']);self.assertEqual(result['error']['code'],'ACCEPTANCE_FILE_PROTECTED')
        self.assertEqual((self.repo/'tests/test_calc.py').read_bytes(),before)
        self.assertFalse((self.server.store.path.parent/'file-recovery').exists())

    async def test_full_access_desktop_has_no_ordinary_approval_but_keeps_binding(self):
        self.grant(confirmed=True)
        self.server.approvals.request=AsyncMock(side_effect=AssertionError('desktop requested approval'))
        self.project.tools.desktop.binding=lambda *_:{'native':{'pid':123,'class':'test','generation':'now'},'title':'owned fixture'}
        execute=AsyncMock(return_value={'ok':True})
        with patch.object(self.server,'_execute_tool_call',execute):
            r=await self.call('desktop_click',{'window_id':'owned','selector':{'name':'Save','control_type':'Button'}})
        self.assertTrue(r['ok']);self.assertTrue(execute.call_args.kwargs['call'].arguments['confirm_risk'])

    async def test_high_risk_and_credential_access_are_not_silently_allowed(self):
        self.grant(confirmed=True)
        self.server.approvals.request=AsyncMock(return_value='deny')
        r=await self.call('run_command',{'command':'git reset --hard HEAD'})
        self.assertFalse(r['ok']);self.server.approvals.request.assert_awaited_once()
        self.assertFalse((await self.call('read_file',{'path':'.env'}))['ok'])
        self.assertFalse((await self.call('run_command',{'command':'Set-MpPreference -DisableRealtimeMonitoring $true'}))['ok'])

    async def test_unknown_operation_replay_still_requires_separate_approval(self):
        self.grant(confirmed=True);self.server.approvals.request=AsyncMock(return_value='deny')
        r=await self.server._authorize_tool(self.ws,project=self.project,call=ToolCall('write_file',{'path':'unknown.txt','content':'x'}),
            call_id='unknown',thread_id=self.thread.id,turn_id='unknown',user_prompt='恢复',uncertain=True)
        self.assertFalse(r['ok']);self.assertFalse((self.repo/'unknown.txt').exists())

    async def test_force_and_deletion_refspecs_cannot_bypass_full_access_git_guard(self):
        self.grant(confirmed=True)
        self.server.approvals.request=AsyncMock(return_value='deny')
        for command in ['git push origin :main','git push origin +HEAD:main','git push --mirror']:
            with self.subTest(command=command):
                self.server.approvals.request.reset_mock()
                result=await self.server._authorize_tool(self.ws,project=self.project,call=ToolCall('run_command',{'command':command}),
                    call_id='refspec',thread_id=self.thread.id,turn_id='refspec',user_prompt='推送普通开发分支')
                self.assertFalse(result['ok']);self.server.approvals.request.assert_awaited_once()

    async def test_role_model_handoffs_share_full_grant_and_real_evidence(self):
        self.grant(confirmed=True);self.server.approvals.request=AsyncMock(side_effect=AssertionError('repeated approval'))
        provider=fixture.ScriptedProvider([
            fixture.tool_step('agent_plan',{'steps':[
                {'task_id':'dev','description':'修复','assigned_role':'developer','dependencies':[]},
                {'task_id':'review','description':'独立审查','assigned_role':'reviewer','dependencies':['dev']},
                {'task_id':'test','description':'测试','assigned_role':'tester','dependencies':['review']}]}),
            fixture.tool_step('write_file',{'path':'calculator.py','content':'def add(a,b): return a+b\n'}),fixture.final_step('实现'),
            fixture.tool_step('read_file',{'path':'calculator.py'}),fixture.tool_step('workflow_review',{'decision':'approved','summary':'实际重新读取'}),fixture.final_step('审查'),
            fixture.tool_step('run_command',{'command':'uv run --no-project python -m unittest discover -s tests -v'}),fixture.final_step('交付')])
        await self.server.run_tool_turn(self.ws,thread_id=self.thread.id,turn_id='full-roles',prompt='修复并审查测试，不推送',model='mock',provider=provider,unified=True)
        r=[e['payload']['runtime'] for e in self.ws.messages if e['type']=='agent.runtime.updated'][-1]
        self.assertEqual(r['outcome'],'completed_verified');self.assertEqual(len(r['role_handoffs']),3)


if __name__=='__main__':unittest.main()
