import copy
from contextlib import nullcontext
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

from agent.core.runtime_events import RuntimeLedger


class ExecutionFixture:
    def __init__(self,db):
        self.db,self.key,self.thread_id=db,'run','thread'
        self.data={'calls':7,'reserved_tokens':12345,'elapsed':20,'unified':{'phase':'executing','generation':'attempt-1'},
                   'unified_api_requests':[{'id':'request-1','status':'reserved','reserved_tokens':900,'estimated':True}]}
        db.execute('CREATE TABLE agent_execution_runs(id TEXT PRIMARY KEY,thread_id TEXT,data_json TEXT)')
        self.save()

    def save(self,commit=True):
        with self.db if commit else nullcontext():
            self.db.execute('INSERT OR REPLACE INTO agent_execution_runs VALUES(?,?,?)',(self.key,self.thread_id,json.dumps(self.data)))


class RuntimeEventTests(unittest.TestCase):
    def setUp(self):
        self.db=sqlite3.connect(':memory:');self.ledger=RuntimeLedger(self.db,lambda:('private-secret',))

    def tearDown(self):self.db.close()

    def test_failure_class_is_derived_from_recorded_error(self):
        observe = self.ledger.request_callback('run', 'thread', 'request', {})
        event = observe('request.failed', {'error_code': 'MODEL_TRUNCATED'})
        self.assertEqual(event['metadata']['failure_class'], 'OUTPUT_TRUNCATED')

    def test_completed_attempt_cannot_regress_or_accept_unknown_phase(self):
        execution=ExecutionFixture(self.db)
        self.ledger.transition(execution,'completed','attempt-1')
        self.assertIsNone(self.ledger.transition(execution,'failed','attempt-1'))
        self.assertIsNone(self.ledger.transition(execution,'executing','attempt-1'))
        self.assertEqual(execution.data['unified']['phase'],'completed')
        with self.assertRaises(ValueError):self.ledger.transition(execution,'invented','attempt-1')

    def test_event_id_is_unique_and_duplicate_client_event_is_idempotent(self):
        first=self.ledger.record('run','thread','request.prepared',{'model':'mock'},event_key='request-1:prepared')
        duplicate=self.ledger.record('run','thread','request.prepared',{'model':'different'},event_key='request-1:prepared')
        self.assertEqual(first,duplicate)
        self.assertEqual(len(self.ledger.events(run_id='run')),1)
        other=self.ledger.record('run','thread','request.dispatched')
        self.assertNotEqual(first['event_id'],other['event_id'])
        self.assertGreater(other['sequence'],first['sequence'])

    def test_private_request_bodies_headers_and_cookie_values_never_enter_events(self):
        event=self.ledger.record('run','thread','request.failed',{
            'prompt':'private prompt','Authorization':'Bearer private-secret','Cookie':'secret-session',
            'model':'private-secret','reason':'Cookie: private-session; account=private-account',
            'http_status':403,'request_sent':True})
        value=json.dumps(event)
        for secret in ['private prompt','private-secret','private-session','private-account','secret-session']:
            self.assertNotIn(secret,value)
        self.assertTrue(event['metadata']['request_sent'])

    def test_queued_message_body_is_durable_but_not_in_trace(self):
        self.assertTrue(self.ledger.enqueue('run','thread','message-1','新增需求正文'))
        self.assertFalse(self.ledger.enqueue('run','thread','message-1','新增需求正文'))
        with self.assertRaises(ValueError):self.ledger.enqueue('run','thread','message-1','不同内容')
        self.assertEqual(self.ledger.pending('run'),[{'message_id':'message-1','text':'新增需求正文'}])
        self.assertNotIn('新增需求正文',json.dumps(self.ledger.events(run_id='run'),ensure_ascii=False))

    def test_failed_apply_rolls_back_queue_budget_and_state_together(self):
        execution=ExecutionFixture(self.db);original=copy.deepcopy(execution.data)
        self.ledger.enqueue('run','thread','message-1','用户追加内容')
        def fail(rows):
            execution.data['calls']=999;execution.data['unified']['phase']='completed'
            execution.save(commit=False)
            raise RuntimeError('故障注入')
        with self.assertRaises(RuntimeError):self.ledger.apply_followups(execution,fail)
        self.assertEqual(execution.data,original)
        self.assertEqual(json.loads(self.db.execute('SELECT data_json FROM agent_execution_runs').fetchone()[0]),original)
        self.assertEqual(len(self.ledger.pending('run')),1)
        self.assertFalse(any(e['kind']=='followup.applied' for e in self.ledger.events(run_id='run')))

    def test_application_is_atomic_and_not_repeated_after_restart(self):
        execution=ExecutionFixture(self.db);self.ledger.enqueue('run','thread','message-1','追加')
        called=[]
        def apply(rows):called.extend(r['message_id'] for r in rows)
        self.ledger.apply_followups(execution,apply)
        restarted=RuntimeLedger(self.db)
        self.assertEqual(restarted.apply_followups(execution,apply),[])
        self.assertEqual(called,['message-1'])
        self.assertEqual(execution.data['calls'],7)

    def test_cancel_is_a_persisted_barrier_for_late_events(self):
        execution=ExecutionFixture(self.db);stale=copy.copy(execution);stale.data=copy.deepcopy(execution.data)
        event=self.ledger.transition(execution,'cancelled','attempt-1')
        self.assertIsNotNone(event)
        self.assertIsNone(self.ledger.transition(stale,'completed','attempt-1'))
        stored=json.loads(self.db.execute('SELECT data_json FROM agent_execution_runs').fetchone()[0])
        self.assertEqual(stored['unified']['phase'],'cancelled')
        self.assertEqual(stored['unified']['event_id'],event['event_id'])
        self.assertEqual(self.ledger.recover_executions(),0)

    def test_old_generation_cannot_overwrite_explicit_new_attempt(self):
        execution=ExecutionFixture(self.db)
        execution.data['unified']['generation']='attempt-2';execution.save()
        self.assertIsNone(self.ledger.transition(execution,'cancelled','attempt-1'))
        self.assertIsNotNone(self.ledger.transition(execution,'executing','attempt-2'))

    def test_crash_recovery_preserves_budget_requests_and_pending_messages(self):
        execution=ExecutionFixture(self.db);self.ledger.enqueue('run','thread','message-1','待恢复需求')
        self.assertEqual(self.ledger.recover_executions(),1)
        value=json.loads(self.db.execute('SELECT data_json FROM agent_execution_runs').fetchone()[0])
        self.assertEqual(value['unified']['phase'],'paused')
        self.assertEqual(value['calls'],7);self.assertEqual(value['reserved_tokens'],12345)
        self.assertEqual(value['unified_api_requests'][0]['status'],'interrupted')
        self.assertEqual(value['unified_api_requests'][0]['reserved_tokens'],900)
        self.assertEqual(len(self.ledger.pending('run')),1)
        self.assertEqual(self.ledger.recover_executions(),0)

    def test_rebinding_plan_keeps_event_ids_and_messages(self):
        event=self.ledger.record('turn','thread','request.prepared')
        self.ledger.enqueue('turn','thread','message-1','需求')
        self.ledger.rebind('turn','plan')
        self.assertEqual(self.ledger.events(run_id='plan')[0]['event_id'],event['event_id'])
        self.assertEqual(len(self.ledger.pending('plan')),1)

    def test_complete_export_does_not_silently_truncate_history(self):
        for i in range(530):self.ledger.record('run','thread','request.prepared',{'attempt':i})
        self.assertEqual(len(self.ledger.events(run_id='run',limit=5000)),500)
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'events.json'
            self.assertEqual(self.ledger.export_run(path,'run'),530)
            self.assertEqual(len(json.loads(path.read_text(encoding='utf-8'))),530)
