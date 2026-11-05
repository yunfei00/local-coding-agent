import asyncio
from datetime import datetime,timezone,timedelta
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from agent.core.model_routing import CapabilityRegistry,requirements,fallback,prohibited,SUPPORTED,UNKNOWN
from agent.core.model_catalog import ModelCatalog,KEY,validate_catalog
from agent.core.settings import RuntimeSettings
from agent.persistence.store import SQLiteStore
from agent.llm.openai_compatible import OpenAICompatibleProvider
from agent.llm.base import ProviderError
from agent.core.context import ContextBudgetManager
from agent.core.execution import ExecutionBudget

class RoutingTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.store=SQLiteStore(self.temp.name)
        self.addCleanup(self.temp.cleanup);self.addCleanup(self.store.close)
        self.catalog=ModelCatalog(self.store,RuntimeSettings.load(self.store))
        self.raw=validate_catalog({'connections':[{'connection_id':'api','display_name':'API','provider_type':'openai_compatible','base_url':'https://example.invalid/v1','credential_reference':None,'enabled':True}],
          'profiles':[{'model_profile_id':pid,'connection_id':'api','model_id':model,'display_name':pid,'context_window':65536,'max_output_tokens':1024} for pid,model in [('a','chat-candidate'),('b','tool-candidate'),('c','vision-candidate'),('blocked','QWEN_3.8_FLASH-2026')]]})
        self.store.set_setting(KEY,json.dumps(self.raw));self.registry=CapabilityRegistry(self.catalog)
        self.seed('a',tools='FAIL',vision='FAIL');self.seed('b',vision='FAIL');self.seed('c')
    def seed(self,pid,*,tools='PASS',vision='PASS',when=None):
        result={'live':True,'configuration':'PASS','text':'PASS','tools':tools,'vision':vision,'tested_at':when or datetime.now(timezone.utc).isoformat(),'config_fingerprint':self.catalog.fingerprint(pid)}
        self.store.set_setting('model.test.'+pid,json.dumps(result))
    async def test_forbidden_aliases_never_create_http_session(self):
        for model in ['qwen3.8-flash','vendor/QWEN_3_8_FLASH:latest','Qwen3.7-Plus-202611','qwen3.7-plus']:
            self.assertTrue(prohibited(model))
            provider=OpenAICompatibleProvider(base_url='https://example.invalid',api_key='inert')
            with patch('agent.llm.openai_compatible.aiohttp.ClientSession') as session:
                with self.assertRaises(ProviderError) as e:
                    async for _ in provider.stream_chat(model=model,messages=[]):pass
                self.assertEqual(e.exception.code,'MODEL_PROHIBITED');session.assert_not_called()
        self.assertFalse(prohibited('qwen3.8-27b'));self.assertFalse(prohibited('qwen3.8-omni-flash-realtime'))
    def test_manual_preferred_and_no_silent_fallback(self):
        chosen,route=self.registry.prepare('profile:b','修复 calculator.py 的加法并测试')
        self.assertEqual(chosen['profile_id'],'b');self.assertFalse(route['allow_fallback'])
        self.assertIsNone(fallback(route,'MODEL_QUOTA_EXHAUSTED'))
        with self.assertRaises(ProviderError):self.registry.prepare('profile:a','修改 Python 文件')
    def test_auto_chat_code_vision_and_explainable_choice(self):
        chat,route=self.registry.prepare('auto','Python 的装饰器是什么？');self.assertEqual(chat['profile_id'],'a');self.assertTrue(chat['reason'])
        code,_=self.registry.prepare('auto','修改 Python 文件并运行测试');self.assertEqual(code['profile_id'],'b')
        vision,_=self.registry.prepare('auto','读取窗口截图并点击按钮');self.assertEqual(vision['profile_id'],'c')
    def test_unknown_not_supported_and_stale_fingerprint_or_age_ignored(self):
        self.store.set_setting('model.test.b','{}');state=self.registry.state(self.raw['profiles'][1]);self.assertEqual(state['capabilities']['tools']['state'],UNKNOWN)
        self.seed('b',when=(datetime.now(timezone.utc)-timedelta(days=31)).isoformat());self.assertEqual(self.registry.state(self.raw['profiles'][1])['capabilities']['chat']['state'],UNKNOWN)
        self.seed('b');self.raw['profiles'][1]['context_window']=60000;self.store.set_setting(KEY,json.dumps(self.raw))
        self.assertEqual(self.registry.state(self.raw['profiles'][1])['capabilities']['tools']['state'],UNKNOWN)
    def test_new_failed_probe_is_not_hidden_by_older_successful_tool_call(self):
        self.registry.record('b',success=True,tools=True)
        self.seed('b',tools='FAIL',when=self.catalog.test_result('b')['tested_at'])
        self.assertEqual(self.registry.state(self.raw['profiles'][1])['capabilities']['tools']['state'],'UNSUPPORTED')
    def test_project_knowledge_request_with_no_code_edit_is_analysis(self):
        from agent.core.unified_runtime import requested_intent
        for prompt in ['检索项目入口，解释技术栈和关键模块，不修改代码。保存项目记忆。','读取工程源码，禁止改动代码。记住：使用 unittest。']:
            intent=requested_intent(prompt)
            self.assertEqual(intent['kind'],'analysis');self.assertTrue(intent['read_only']);self.assertTrue(intent['memory_write'])
        self.assertEqual(requested_intent('修复 mathcore.py，但不要修改测试')['kind'],'change')
    def test_no_file_edits_boundary_does_not_disable_explicit_gui_actions(self):
        from agent.core.unified_runtime import requested_intent,computer_only
        goal='使用桌面工具操作窗口，点击按钮并读取结果。禁止读取 HTML/JS 源码，不得修改任何文件。'
        self.assertEqual(requested_intent(goal)['kind'],'interaction');self.assertFalse(requested_intent(goal)['read_only']);self.assertTrue(computer_only(goal))
        self.assertEqual(requested_intent('只分析窗口中的按钮如何点击，不要操作桌面')['kind'],'analysis')
    def test_explicit_environment_maintenance_does_not_require_business_file_changes(self):
        from agent.core.unified_runtime import requested_intent
        intent=requested_intent('使用 environment_diagnose 检查 Git PATH，使用 environment_repair 申请项目级修复，然后运行 unittest。')
        self.assertEqual(intent['kind'],'analysis');self.assertTrue(intent['read_only']);self.assertTrue(intent['environment_write'])
        self.assertFalse(requested_intent('只分析环境，禁止修复代理')['environment_write'])
        self.assertEqual(requested_intent('修复 calculator.py 加法并修复依赖环境')['kind'],'change')
    def test_quota_failure_disables_future_candidate_until_success(self):
        chosen,route=self.registry.prepare('auto','修复代码并执行工具')
        self.registry.record(chosen['profile_id'],error='MODEL_QUOTA_EXHAUSTED')
        self.assertNotIn(chosen['profile_id'],[r['profile_id'] for r in self.registry.candidates(route['requirements'])])
        next_one=fallback(route,'MODEL_QUOTA_EXHAUSTED');self.assertEqual(next_one['profile_id'],'c')
        with self.assertRaises(ProviderError) as error:fallback(route,'MODEL_QUOTA_EXHAUSTED')
        self.assertEqual(error.exception.code,'MODEL_CANDIDATES_EXHAUSTED')
        self.registry.record(chosen['profile_id'],success=True,tools=True)
        self.assertIn(chosen['profile_id'],[r['profile_id'] for r in self.registry.candidates(route['requirements'])])
    def test_same_actual_model_alias_is_deduplicated_and_quota_cannot_be_bypassed(self):
        alias={**self.raw['profiles'][1],'model_profile_id':'b-alias','display_name':'别名'};self.raw['profiles'].append(alias);self.store.set_setting(KEY,json.dumps(self.raw));self.seed('b-alias',vision='FAIL')
        need=requirements('修复代码');rows=self.registry.candidates(need)
        self.assertEqual(sum(r['snapshot']['profile']['model']=='tool-candidate' for r in rows),1)
        self.registry.record('b',error='MODEL_QUOTA_EXHAUSTED')
        self.assertNotIn('b-alias',[r['profile_id'] for r in self.registry.candidates(need)])
    def test_corrupt_probe_cache_does_not_erase_configuration_or_claim_support(self):
        self.store.set_setting('model.test.b','{broken');state=self.registry.state(self.raw['profiles'][1])
        self.assertEqual(state['capabilities']['tools']['state'],UNKNOWN);self.assertEqual(self.catalog.load()['profiles'][1]['model_id'],'tool-candidate')
    def test_network_auth_and_rate_limit_do_not_rotate(self):
        _,route=self.registry.prepare('auto','修复代码')
        for error in ['OPENAI_COMPATIBLE_CONNECTION_FAILED','DNS_FAILED','OPENAI_COMPATIBLE_AUTH_FAILED','OPENAI_COMPATIBLE_RATE_LIMITED']:
            self.assertIsNone(fallback(route,error))
        self.assertEqual(route['switches'],[])
        self.assertIsNone(fallback(route,'OPENAI_COMPATIBLE_REQUEST_FAILED',http_status=400))
        self.assertIsNotNone(fallback(route,'OPENAI_COMPATIBLE_REQUEST_FAILED',http_status=503))
    def test_invalid_health_cache_and_changed_config_evidence_are_safe(self):
        for value in ['[]','{"successes":"invalid"}','null',json.dumps({'fingerprint':self.catalog.fingerprint('b'),'detected_at':None})]:
            self.store.set_setting(self.registry.key('b'),value)
            self.assertEqual(self.registry.state(self.raw['profiles'][1])['capabilities']['tools']['state'],SUPPORTED)
        fingerprint=self.catalog.fingerprint('b')
        self.raw['profiles'][1]['context_window']=60000;self.store.set_setting(KEY,json.dumps(self.raw))
        self.registry.record('b',success=True,tools=True,expected_fingerprint=fingerprint)
        self.assertEqual(self.registry.state(self.raw['profiles'][1])['capabilities']['tools']['state'],UNKNOWN)
    def test_context_timeout_capability_failure_can_choose_only_confirmed_alternative(self):
        for error in ['MODEL_CONTEXT_LIMIT','MODEL_REQUEST_TIMEOUT','MODEL_TOOLS_UNAVAILABLE']:
            _,route=self.registry.prepare('auto','修复代码');self.assertEqual(fallback(route,error)['profile_id'],'c')
    def test_http_quota_and_retry_after_are_typed_without_body_leak(self):
        provider=OpenAICompatibleProvider();provider.response_metadata={'retry_after':3}
        error=provider._http_error(403,{'error':{'code':'AllocationQuota.FreeTierOnly','message':'sensitive-body'}},'请求失败')
        self.assertEqual(error.code,'MODEL_QUOTA_EXHAUSTED');self.assertNotIn('sensitive-body',error.message)
        retry=provider._http_error(429,{},'限流');self.assertEqual(retry.retry_after,3);self.assertTrue(retry.transient)
        provider.response_metadata={'retry_after':120}
        self.assertFalse(provider._http_error(429,{},'限流').transient)
    def test_routing_snapshot_does_not_change_with_settings_or_reset_budget(self):
        from agent.llm.router import validate_config
        self.store.set_setting('orchestration.config',json.dumps(validate_config({'budget':{'request_seconds':61}})))
        chosen,route=self.registry.prepare('auto','修复代码');serialized=json.dumps(route)
        self.assertEqual(chosen['snapshot']['request_seconds'],61)
        self.store.set_setting('orchestration.config',json.dumps(validate_config({'budget':{'request_seconds':2}})))
        self.raw['profiles'][2]['model_id']='changed-model';self.store.set_setting(KEY,json.dumps(self.raw))
        self.assertEqual(json.dumps(route),serialized)
        alternative=fallback(route,'MODEL_QUOTA_EXHAUSTED')
        self.assertEqual(alternative['snapshot']['profile']['model'],'vision-candidate');self.assertEqual(alternative['snapshot']['request_seconds'],61)
    def test_context_compaction_preserves_goal_and_tool_pairs(self):
        manager=ContextBudgetManager(context_window_tokens=2048,reserved_output_tokens=256,compression_threshold=.7)
        messages=[{'role':'system','content':'必须保留的权限规则'},{'role':'user','content':'原始目标：修复计算器，保留完成步骤'}]
        for i in range(20):messages.extend([{'role':'assistant','content':'','tool_calls':[{'id':str(i),'type':'function','function':{'name':'read_file','arguments':'{}'}}]},{'role':'tool','tool_call_id':str(i),'content':'reconstructable data '*150}])
        fitted=manager.fit_runtime(messages,history_messages_total=0)
        self.assertIn('原始目标',fitted.messages[1]['content']);self.assertGreater(fitted.usage.runtime_messages_omitted,0)
        ids={c['id'] for m in fitted.messages for c in m.get('tool_calls',[])}
        self.assertTrue(all(m.get('tool_call_id') in ids for m in fitted.messages if m['role']=='tool'))
    def test_tool_stage_budget_and_restart_are_cumulative(self):
        limits={'model_calls':3,'tokens':10000,'seconds':120,'max_continuations':1,'tool_calls':1,'stage_tokens':100}
        budget=ExecutionBudget(self.store.connection,'test','thread',limits);budget.reserve_tool()
        reopened=ExecutionBudget(self.store.connection,'test','thread',limits)
        with self.assertRaises(ProviderError) as e:reopened.reserve_tool()
        self.assertEqual(e.exception.code,'TOOL_BUDGET_EXHAUSTED')
        with self.assertRaises(ProviderError) as e:reopened.reserve([{'content':'x'*1000}],None,20,stage='planning')
        self.assertEqual(e.exception.code,'STAGE_BUDGET_EXHAUSTED');self.assertEqual(reopened.data['calls'],0)
    async def test_diagnostic_stops_after_quota_even_if_text_previously_succeeded(self):
        from agent.core.model_diagnostics import ModelDiagnostics
        from agent.llm.base import ProviderChunk
        class Probe:
            api_key='synthetic-test-credential'
            calls=0
            response_metadata={}
            async def stream_chat(self,**request):
                self.calls+=1
                if self.calls>1:raise ProviderError('MODEL_QUOTA_EXHAUSTED','模拟额度耗尽')
                yield ProviderChunk(content='LCA_OK',done=True)
        provider=Probe()
        report=await ModelDiagnostics().run(provider,self.raw['connections'][0],self.raw['profiles'][1],live=True,vision=True)
        self.assertEqual(provider.calls,2);self.assertEqual(report['tools'],'NOT RUN')
        self.assertEqual(report['errors'][-1]['code'],'MODEL_QUOTA_EXHAUSTED')
