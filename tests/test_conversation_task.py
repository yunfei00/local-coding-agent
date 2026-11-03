import sqlite3
import unittest
from agent.task_plans import TaskPlanStore
from agent.core.task_runtime import TaskRuntimeStore
from agent.llm.router import validate_config
from agent.core.budget import BudgetGuard


class ConversationContinuationTests(unittest.TestCase):
    def test_followup_keeps_plan_identity_completed_evidence_budget_and_is_idempotent(self):
        db=sqlite3.connect(':memory:'); db.row_factory=sqlite3.Row
        plans=TaskPlanStore(db); runtime=TaskRuntimeStore(plans)
        task=runtime.create('thread','original goal',validate_config({}),'workspace')
        guard=BudgetGuard(runtime,task['id'],task['config']['budget'])
        request=guard.reserve(route='api',role='executor',model='mock',messages=[{'role':'user','content':'goal'}],tools=None,context_window=65536,output_limit=100)
        guard.finish(request,'completed',{'input_tokens':20,'output_tokens':10,'estimated':False})
        original_usage=runtime.usage(task['id'])
        step=plans.get(task['id'])['steps'][0]
        plans.update_step(task['id'],step['id'],'completed',[{'tool':'test','exit_code':0}])
        runtime.transition(task['id'],'paused')
        before=runtime.get(task['id'])['config']
        self.assertTrue(runtime.append_followup(task['id'],'Add validation','message-1'))
        self.assertFalse(runtime.append_followup(task['id'],'Add validation','message-1'))
        restored=TaskRuntimeStore(plans).get(task['id'])
        self.assertEqual(restored['config'],before)
        self.assertIn('original goal',restored['goal'])
        self.assertEqual(len(plans.get(task['id'])['steps']),2)
        self.assertEqual(plans.get(task['id'])['steps'][0]['state'],'completed')
        self.assertEqual(plans.get(task['id'])['steps'][1]['state'],'pending')
        self.assertEqual(runtime.usage(task['id']),original_usage)
        self.assertEqual(runtime.usage(task['id'])['api_calls'],1)
        db.close()

    def test_invalid_followup_does_not_add_steps(self):
        db=sqlite3.connect(':memory:'); runtime=TaskRuntimeStore(TaskPlanStore(db))
        task=runtime.create('thread','goal',validate_config({}),'workspace')
        with self.assertRaises(ValueError):runtime.append_followup(task['id'],'text','id')
        runtime.transition(task['id'],'paused')
        with self.assertRaises(ValueError):runtime.append_followup(task['id'],'x'*4001,'id')
        self.assertEqual(len(runtime.plans.get(task['id'])['steps']),1)
        db.close()
