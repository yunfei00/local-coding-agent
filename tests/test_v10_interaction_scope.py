"""GUI scope regressions: mock model/desktop; real isolated workspace assertions."""
import unittest
from unittest.mock import AsyncMock
from agent.core.unified_runtime import requested_intent

GOAL='这是 Windows 界面操作验收，不是开发任务。在窗口中输入验收内容，点击保存，读取 gui-saved.txt，禁止修改夹具源码，不得运行代码测试。'


class InteractionIntentTests(unittest.TestCase):
    def test_negated_development_is_an_interaction(self):
        self.assertEqual(requested_intent(GOAL)['kind'],'interaction')

    def test_actual_development_with_gui_keeps_code_verification(self):
        self.assertEqual(requested_intent('开发 calculator.py 并在窗口中输入数字点击验证')['kind'],'change')


class InteractionScopeTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        from test_unified_runtime import UnifiedLoopTests
        self.fixture=UnifiedLoopTests('runTest');await self.fixture.asyncSetUp()

    async def asyncTearDown(self):
        await self.fixture.asyncTearDown()

    async def run_script(self,steps,**kwargs):
        from test_agent_reliability import ScriptedProvider
        f=self.fixture
        await f.server.run_tool_turn(f.ws,thread_id=f.thread.id,turn_id='v10-gui-scope',prompt=kwargs.pop('prompt',GOAL),model='mock',provider=ScriptedProvider(steps),unified=True,**kwargs)
        return [e['payload']['runtime'] for e in f.ws.messages if e['type']=='agent.runtime.updated'][-1]

    async def test_gui_result_does_not_trigger_unrelated_failing_code_tests(self):
        from test_agent_reliability import tool_step,final_step
        f=self.fixture
        async def save(*args,**kwargs):
            (f.repo/'gui-saved.txt').write_text('actual unit fixture output')
            return {'ok':True,'changed_paths':['gui-saved.txt']}
        f.server._authorize_tool=AsyncMock(side_effect=save)
        result=await self.run_script([tool_step('desktop_click',{'window_id':'owned-test','selector':{'name':'Save'}}),final_step('界面保存已完成')])
        self.assertEqual(result['phase'],'completed')
        self.assertEqual(result['intent'],'interaction')
        self.assertEqual(result['verification'],[])
        self.assertEqual(result['outcome'],'completed_unverified')
        self.assertIn('gui-saved.txt',result['changed_paths'])
        self.assertIn('a-b',(f.repo/'calculator.py').read_text())
        self.assertEqual(f.server._authorize_tool.await_count,1)

    async def test_old_misclassified_snapshot_recovers_original_gui_scope(self):
        from agent.core.execution import ExecutionBudget
        from test_agent_reliability import tool_step,final_step
        f=self.fixture
        execution=ExecutionBudget(f.server.store.connection,'legacy-gui',f.thread.id,f.server.continuation_policy)
        execution.data.update(unified={'intent':'complex','phase':'failed'},unified_goal=GOAL,
                              unified_request=requested_intent('开发计算器代码'))
        execution.save()
        f.server._authorize_tool=AsyncMock(return_value={'ok':True,'changed_paths':[]})
        result=await self.run_script([tool_step('desktop_click',{'window_id':'owned-test','selector':{'name':'Save'}}),final_step('已有工具证据')],prompt='继续未完成步骤',execution_id='legacy-gui')
        self.assertEqual(result['phase'],'completed')
        self.assertEqual(result['intent'],'interaction')
        self.assertEqual(result['verification'],[])

    async def test_prose_alone_is_not_gui_success(self):
        from test_agent_reliability import final_step
        result=await self.run_script([final_step('界面保存成功')])
        self.assertEqual(result['error_code'],'AGENT_NO_INTERACTION_EVIDENCE')

    async def test_model_cannot_write_unrelated_code_in_gui_task(self):
        from test_agent_reliability import tool_step
        f=self.fixture;f.server._authorize_tool=AsyncMock()
        result=await self.run_script([tool_step('write_file',{'path':'forged.py','content':'bad'})])
        self.assertEqual(result['error_code'],'COMPUTER_TOOL_SCOPE')
        f.server._authorize_tool.assert_not_awaited()
        self.assertFalse((f.repo/'forged.py').exists())

    async def test_model_cannot_run_code_test_or_shell_repair_in_gui_task(self):
        from test_agent_reliability import tool_step
        f=self.fixture;f.server._authorize_tool=AsyncMock()
        result=await self.run_script([tool_step('run_command',{'command':'uv run --no-project python -m unittest discover -s tests -v'})])
        self.assertEqual(result['error_code'],'COMPUTER_TOOL_SCOPE')
        f.server._authorize_tool.assert_not_awaited()
