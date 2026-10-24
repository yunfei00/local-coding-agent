"""Offline guard tests. These never claim real inference or send paid requests."""
import importlib.util
import base64
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from agent.core.model_catalog import KEY
from agent.persistence.store import SQLiteStore
from agent.llm.openai_compatible import request_image_evidence

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / 'scripts/validation/real_online_agent_e2e.py'
spec = importlib.util.spec_from_file_location('live_acceptance', SCRIPT)
live = importlib.util.module_from_spec(spec)
spec.loader.exec_module(live)


def catalog():
    return {'connections':[{'connection_id':'api','display_name':'Controlled',
        'provider_type':'openai_compatible','enabled':True,'base_url':'https://example.test/v1',
        'credential_reference':'connection-api'}], 'profiles':[
            {'connection_id':'api','model_profile_id':'qwen','model_id':'qwen3.8-flash',
             'display_name':'Qwen','supports_vision':True},
            {'connection_id':'api','model_profile_id':'glm','model_id':'glm-5.3',
             'display_name':'GLM','supports_vision':False}]}


class LiveAcceptanceGuards(unittest.TestCase):
    def test_wire_image_evidence_fingerprints_bytes_without_retaining_content_or_urls(self):
        pixels = b'controlled-test-pixels'
        image = 'data:image/jpeg;base64,'+base64.b64encode(pixels).decode()
        messages = [{'role':'user','content':[{'type':'text','text':'private prompt'},
                    {'type':'image_url','image_url':{'url':image}},
                    {'type':'image_url','image_url':{'url':'https://private.example/image'}}]}]
        evidence = request_image_evidence(messages)
        self.assertEqual(evidence,[{'mime_type':'image/jpeg','bytes':len(pixels),
                                   'sha256':hashlib.sha256(pixels).hexdigest()}])
        serialized = json.dumps(evidence)
        for private in ('private','controlled-test-pixels',image,'https://'):
            self.assertNotIn(private,serialized)
    def test_selects_exact_identity_and_glm_is_not_required_to_have_vision(self):
        saved = catalog()
        self.assertEqual(live.select_profile(saved,'glm-5.3')['model_profile_id'],'glm')
        with self.assertRaisesRegex(ValueError,'VISION_CAPABILITY'):
            live.select_profile(saved,'glm-5.3',vision=True)
        with self.assertRaisesRegex(ValueError,'MISSING_OR_AMBIGUOUS'):
            live.select_profile(saved,'qwen3.8-max')

    def test_same_named_models_require_explicit_connection_identity(self):
        saved = catalog()
        saved['profiles'].append({**saved['profiles'][0],'model_profile_id':'other'})
        with self.assertRaisesRegex(ValueError,'AMBIGUOUS'):
            live.select_profile(saved,'qwen3.8-flash')
        self.assertEqual(live.select_profile(saved,'qwen3.8-flash','other')['model_profile_id'],'other')
        saved['connections'][0]['enabled'] = False
        with self.assertRaises(ValueError):
            live.select_profile(saved,'qwen3.8-flash','other')

    def test_unknown_currency_prices_never_allow_40_request_default(self):
        qwen = catalog()['profiles'][0]
        config = live.live_config(qwen,qwen,12)
        self.assertEqual(config['budget']['global_api_calls'],12)
        self.assertEqual(config['budget']['global_api_tokens'],60000)
        self.assertEqual(config['budget']['request_seconds'],60)
        self.assertEqual(config['budget']['task_seconds'],900)
        for calls in (0,13,41,True):
            with self.assertRaises(ValueError):
                live.live_config(qwen,qwen,calls)

    def test_readonly_inventory_does_not_create_missing_user_database(self):
        with tempfile.TemporaryDirectory() as temp:
            with self.assertRaisesRegex(ValueError,'CATALOG_UNAVAILABLE'):
                live.load_catalog(Path(temp))
            self.assertFalse(list(Path(temp).iterdir()))

    def test_crash_keeps_session_reservation_and_glm_waits_for_qwen(self):
        with tempfile.TemporaryDirectory() as temp:
            session = Path(temp)/'session.json'
            with self.assertRaisesRegex(ValueError,'QWEN_ACCEPTANCE_REQUIRED'):
                live.allocate_session(session,'glm-5.3',12)
            remaining = live.allocate_session(session,'qwen3.8-flash',12)
            self.assertEqual(remaining,{'calls':12,'tokens':60000,'seconds':900})
            with self.assertRaisesRegex(ValueError,'UNSETTLED'):
                live.allocate_session(session,'qwen3.8-flash',12)

    def test_session_retries_cannot_reset_calls_tokens_time_or_grow_ceiling(self):
        with tempfile.TemporaryDirectory() as temp:
            session = Path(temp)/'session.json'
            session.write_text(json.dumps({'call_ceiling':8,'attempts':[
                {'model':'qwen3.8-flash','state':'settled','result':'PASS',
                 'calls':5,'tokens':22000,'seconds':90}]}))
            remaining = live.allocate_session(session,'glm-5.3',12)
            self.assertEqual(remaining,{'calls':3,'tokens':38000,'seconds':810})
            state = json.loads(session.read_text())
            state['attempts'][-1].update(state='settled',calls=3,tokens=1000,seconds=10)
            session.write_text(json.dumps(state))
            with self.assertRaisesRegex(ValueError,'BUDGET_EXHAUSTED'):
                live.allocate_session(session,'qwen3.8-flash',12)

    def test_explicit_authorized_update_preserves_all_existing_usage(self):
        with tempfile.TemporaryDirectory() as temp:
            session = Path(temp)/'session.json'
            session.write_text(json.dumps({'call_ceiling':12,'attempts':[
                {'model':'qwen3.8-flash','task_id':'first','state':'settled','result':'FAIL','calls':2,'tokens':10872,'seconds':10},
                {'model':'qwen3.8-flash','task_id':'retry','state':'settled','result':'FAIL','calls':4,'tokens':25729,'seconds':29}]}))
            with self.assertRaisesRegex(ValueError,'RETRY_LIMIT'):
                live.allocate_session(session,'qwen3.8-flash',12)
            remaining = live.allocate_session(session,'qwen3.8-flash',40,200000,3,True)
            self.assertEqual(remaining,{'calls':34,'tokens':163399,'seconds':861})
            updated = json.loads(session.read_text())
            self.assertEqual(updated['attempts'][0]['calls'],2)
            self.assertEqual(updated['budget_updates'][0]['used_tokens'],36601)
            profile = catalog()['profiles'][0]
            self.assertEqual(live.live_config(profile,profile,34,163399,True)['budget']['api_calls'],34)

    def test_preparation_preserves_fixture_and_user_storage_without_copying_secrets(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / 'original';source.mkdir()
            store = SQLiteStore(source)
            store.set_setting(KEY,json.dumps(catalog()))
            store.set_setting('private.test','User data must not migrate')
            store.connection.close()
            encrypted = b'{"encrypted":"opaque-test-ciphertext"}'
            (source/'model-secrets.json').write_bytes(encrypted)
            isolated = root/'isolated';isolated.mkdir()
            normalized = live.load_catalog(source)
            profile = live.select_profile(normalized,'qwen3.8-flash')
            manifest = json.loads(live.prepare(source,normalized,profile,profile,12,isolated).read_text())
            self.assertNotIn('opaque-test-ciphertext',json.dumps(manifest))
            self.assertEqual((source/'model-secrets.json').read_bytes(),encrypted)
            self.assertFalse((isolated/'data/model-secrets.json').exists())
            self.assertEqual(Path(manifest['credential_data']),source.resolve())
            app = (isolated/'fixture/src/App.tsx').read_text()
            self.assertIn('disabled={true}',app)
            self.assertIn("setStatus('Not saved');",app)
            copied = SQLiteStore(isolated/'data')
            self.assertIsNone(copied.get_setting('private.test'))
            self.assertEqual(copied.connection.execute('SELECT COUNT(*) FROM messages').fetchone()[0],0)
            copied.connection.close()

    def test_fourth_attempt_needs_explicit_update_and_keeps_remaining_cumulative_caps(self):
        with tempfile.TemporaryDirectory() as temp:
            session=Path(temp)/'session.json'
            session.write_text(json.dumps({'call_ceiling':40,'token_ceiling':200000,
                'attempt_limits':{'qwen3.8-flash':3},'attempts':[
                    {'model':'qwen3.8-flash','task_id':str(i),'state':'settled','result':'FAIL',
                     'calls':calls,'tokens':tokens,'seconds':seconds}
                    for i,(calls,tokens,seconds) in enumerate([(2,10872,9.944),(4,25729,28.748),(14,103253,141.183)])]}))
            with self.assertRaisesRegex(ValueError,'RETRY_LIMIT'):
                live.allocate_session(session,'qwen3.8-flash',40,200000,4)
            remaining=live.allocate_session(session,'qwen3.8-flash',40,200000,4,True)
            self.assertEqual(remaining,{'calls':20,'tokens':60146,'seconds':720})
            state=json.loads(session.read_text())
            self.assertEqual(state['budget_updates'][-1]['used_tokens'],139854)
            self.assertEqual(state['budget_updates'][-1]['new'],{'calls':40,'tokens':200000,'attempts':4})

    def test_work_driven_explicit_caps_stay_bounded_and_preserve_usage_and_time(self):
        with tempfile.TemporaryDirectory() as temp:
            session=Path(temp)/'session.json'
            session.write_text(json.dumps({'call_ceiling':40,'token_ceiling':200000,
                'attempts':[{'model':'qwen3.8-flash','task_id':'previous','state':'settled','result':'FAIL',
                             'calls':20,'tokens':139854,'seconds':179.875}]}))
            remaining=live.allocate_session(session,'qwen3.8-flash',80,500000,6,True,1800)
            self.assertEqual(remaining,{'calls':60,'tokens':360146,'seconds':1620})
            state=json.loads(session.read_text())
            self.assertEqual(state['budget_updates'][-1]['previous_seconds'],900)
            self.assertEqual(state['budget_updates'][-1]['new_seconds'],1800)
            profile=catalog()['profiles'][0]
            config=live.live_config(profile,profile,remaining['calls'],remaining['tokens'],True)
            self.assertEqual(config['budget']['global_api_calls'],60)
            self.assertEqual(config['budget']['global_api_tokens'],360146)
            self.assertEqual(config['budget']['request_seconds'],60)

    def test_lost_task_start_reply_never_refunds_unknown_paid_usage(self):
        with tempfile.TemporaryDirectory() as temp:
            session=Path(temp)/'session.json'
            live.allocate_session(session,'qwen3.8-flash',12)
            with patch.object(live,'REPORT',Path(temp)/'report.json'):
                live.settle_session(session,{'result':'FAIL','controller_stage':'task_start','paid_requests':None,
                                             'usage_uncertain':True})
            state=json.loads(session.read_text())
            self.assertEqual(state['attempts'][-1]['state'],'reserved')
            self.assertEqual(state['attempts'][-1]['tokens'],60000)
            with self.assertRaisesRegex(ValueError,'UNSETTLED'):
                live.allocate_session(session,'qwen3.8-flash',12)

    def test_confirmed_preflight_timeout_has_no_task_or_paid_usage(self):
        with tempfile.TemporaryDirectory() as temp:
            session=Path(temp)/'session.json'
            live.allocate_session(session,'qwen3.8-flash',12)
            with patch.object(live,'REPORT',Path(temp)/'report.json'):
                live.settle_session(session,{'result':'NOT RUN','controller_stage':'electron_launch','paid_requests':0})
            state=json.loads(session.read_text())
            self.assertEqual(state['attempts'][-1]['state'],'settled')
            self.assertEqual(state['attempts'][-1]['tokens'],0)

    @unittest.skipUnless(shutil.which('node'),'Node required for offline controller guard test')
    def test_controller_rejects_unscoped_approvals_and_false_completion(self):
        # Require only helper exports, never launch Electron or a provider.
        script = r"""
const assert=require('node:assert/strict');
const {approvalAllowed,safeCall,finalResult}=require('./scripts/validation/real_online_agent_e2e.cjs');
const pids=new Set([123]);
assert(!approvalAllowed({tool:'desktop_list_windows',arguments:{}},'',pids,'executing'));
assert(approvalAllowed({tool:'desktop_list_windows',arguments:{pid:123}},'',pids,'executing'));
assert(approvalAllowed({tool:'desktop_list_windows',arguments:{}},'',pids,'verifying'));
assert(!approvalAllowed({tool:'desktop_screenshot',arguments:{scope:'screen',target_window:{title:'M5 Electron acceptance',pid:123}}},'',pids));
assert(!approvalAllowed({tool:'desktop_screenshot',arguments:{target_window:{title:'Private editor',pid:123}}},'',pids));
assert(!approvalAllowed({tool:'desktop_click',arguments:{target_window:{title:'M5 Electron acceptance',pid:999},selector:{name:'Save'}}},'',pids));
assert(approvalAllowed({tool:'desktop_screenshot',arguments:{share_with_model:true,target_window:{title:'M5 Electron acceptance',pid:123}}},'',pids));
assert(!approvalAllowed({tool:'run_command',arguments:{command:'npm test; git push'}},'',pids));
assert(!approvalAllowed({tool:'git_commit',arguments:{}},'',pids));
assert.equal(finalResult({status:'awaiting_approval',verification:[{ok:true}],calls:[]},[]).result,'FAIL');
const filtered=safeCall({id:'call',usage:{http_status:200,prompt:'private',api_key:'private',image_url:'private'}});
assert(!JSON.stringify(filtered).includes('private'));
"""
        subprocess.run(['node','-e',script],cwd=ROOT,check=True,capture_output=True)


if __name__ == '__main__':
    unittest.main()
