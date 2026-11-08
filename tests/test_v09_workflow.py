import sqlite3
import unittest
import hashlib

from agent.core.workflow import normalize_nodes, ready_steps, progress, role_allows, scheduling_conflict
from agent.task_plans import TaskPlanStore
from agent.core.workflow_templates import load_templates, expand_template
from agent.core.background import BackgroundJobs


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(':memory:')
        self.addCleanup(self.db.close)
        self.store = TaskPlanStore(self.db)

    def create(self):
        return self.store.create('thread','goal',[
            {'task_id':'review','description':'独立检查','assigned_role':'reviewer','dependencies':['fix']},
            {'task_id':'fix','description':'修复缺陷','assigned_role':'developer','dependencies':[]},
            {'task_id':'tests','description':'测试','assigned_role':'tester','dependencies':['review'],'verification':'uv run python -m unittest'},
        ])

    def test_negative_assertion_does_not_poison_positive_step_evidence(self):
        pid = self.store.create("thread", "verify CLI", [{"task_id":"verify", "description":"verify",
            "assigned_role":"tester", "acceptance_criteria":["run tests"]}])
        step = self.store.active_step(pid)["id"]
        negative = {"ok": True, "exit_code": 2, "data": {"command_outcome":{"status":"expected_exit"}}}
        self.store.record_execution(pid, step, "negative", "turn", "run_command", negative)
        evidence = [{"ok":True,"step_id":step,"tool_call_id":"negative","tool":"run_command","exit_code":2}]
        self.assertFalse(self.store.advance_verified(pid, step, evidence, True))
        self.store.record_execution(pid, step, "positive", "turn", "run_command", {"ok":True,"exit_code":0})
        evidence.append({"ok":True,"step_id":step,"tool_call_id":"positive","tool":"run_command","exit_code":0})
        self.assertTrue(self.store.advance_verified(pid, step, evidence, True))

    def test_missing_test_repair_is_bounded_without_forging_failure_evidence(self):
        pid = self.store.create("thread","verify", [{"task_id":"verify","description":"verify",
            "assigned_role":"tester","acceptance_criteria":["run tests"]}])
        original = self.store.active_step(pid)
        self.assertTrue(self.store.prepare_missing_test_handoff(pid,original["id"]))
        developer = self.store.active_step(pid)
        self.assertEqual(developer["workflow"]["assigned_role"], "developer")
        self.assertEqual(developer["workflow"]["handoff_for"], original["id"])
        self.assertEqual(self.store.executions(pid), [])
        self.store.record_execution(pid,developer["id"],"write","turn","write_file",{"ok":True})
        self.store.update_step(pid,developer["id"],"completed",
                              [{"tool_call_id":"write","step_id":developer["id"],"ok":True}])
        self.assertFalse(self.store.prepare_missing_test_handoff(pid,original["id"]))
        self.assertEqual(self.store.active_step(pid)["state"], "blocked")

    def test_ready_respects_forward_dependency_and_evidence(self):
        pid = self.create()
        first = self.store.active_step(pid)
        self.assertEqual(first['workflow']['task_id'],'fix')
        self.assertFalse(self.store.advance_verified(pid,self.store.get(pid)['steps'][0]['id'],[{'ok':True}],True))
        self.store.record_execution(pid,first['id'],'call-1','turn','write_file',{'ok':True})
        evidence=[{'tool_call_id':'call-1','step_id':first['id'],'tool':'write_file','ok':True}]
        self.assertTrue(self.store.advance_verified(pid,first['id'],evidence,True))
        self.assertEqual(self.store.active_step(pid)['workflow']['task_id'],'review')
        self.store.update_step(pid,first['id'],'blocked')
        self.assertEqual(self.store.active_step(pid)['workflow']['task_id'],'review')
        self.assertEqual(progress(self.store.get(pid)['steps'])['completed'],1)

    def test_invalid_graph_never_writes_partial_plan(self):
        invalid = [
            [{'task_id':'x','description':'x','dependencies':['x']}],
            [{'task_id':'x','description':'x','dependencies':['missing']}],
            [{'task_id':'x','description':'x'},{'task_id':'x','description':'y'}],
            [{'task_id':'x','description':'x','acceptance_criteria':[]}],
            [{'task_id':'x','description':'x','assigned_role':'administrator'}],
        ]
        for nodes in invalid:
            with self.subTest(nodes=nodes), self.assertRaises(ValueError):
                self.store.create('t','goal',nodes)
        self.assertEqual(self.store.list_for_thread('t'),[])

    def test_pending_revision_is_validated_atomically(self):
        pid=self.create()
        self.store.revise_workflow(pid,{'review':{'title':'兼容性审查'}},'需求补充')
        self.assertEqual(self.store.get(pid)['steps'][0]['workflow']['title'],'兼容性审查')
        before=self.store.get(pid)['steps']
        with self.assertRaises(ValueError):
            self.store.revise_workflow(pid,{'fix':{'dependencies':['tests']}},'循环')
        self.assertEqual(before,self.store.get(pid)['steps'])
        with self.assertRaises(ValueError):
            self.store.revise_workflow(pid,{'review':{'assigned_role':'developer'}},'不能降低独立审查边界')

    def test_followup_extends_same_graph_and_keeps_review_test_boundaries(self):
        pid=self.create();before=self.store.get(pid)['steps']
        self.store.append_steps(pid,[{'description':'追加输入校验'}])
        after=self.store.get(pid)['steps']
        self.assertEqual([s['id'] for s in after[:3]],[s['id'] for s in before])
        self.assertEqual([s['workflow']['assigned_role'] for s in after[3:]],['developer','reviewer','tester'])
        self.assertEqual(after[3]['workflow']['dependencies'],['tests'])

    def test_blocked_dependency_does_not_run_dependent(self):
        pid=self.create()
        first=self.store.active_step(pid)
        self.store.update_step(pid,first['id'],'blocked')
        self.assertEqual(self.store.active_step(pid)['id'],first['id'])
        self.assertEqual(ready_steps(self.store.get(pid)['steps']),[])
        second=self.store.get(pid)['steps'][0]
        self.assertFalse(self.store.advance_verified(pid,second['id'],[{'ok':True}],True))
        self.assertTrue(self.store.get(pid)['steps'][0]['dependency_blocked'])
        self.store.update_step(pid,first['id'],'in_progress')
        self.store.record_execution(pid,first['id'],'fixed','turn','write_file',{'ok':True})
        self.store.update_step(pid,first['id'],'completed',self.store.execution_evidence(pid,first['id'],['fixed']))
        self.assertEqual(self.store.active_step(pid)['workflow']['task_id'],'review')
        self.assertEqual(self.store.get(pid)['steps'][0]['state'],'pending')

    def test_roles_restrict_effects_without_granting_permissions(self):
        for role in ('planner','reviewer','tester'):
            self.assertFalse(role_allows(role,'write_file',{},read_only=False))
            self.assertFalse(role_allows(role,'desktop_click',{},read_only=True))
            self.assertFalse(role_allows(role,'environment_repair',{},read_only=True))
            self.assertTrue(role_allows(role,'read_file',{},read_only=True))
        self.assertTrue(role_allows('tester','run_command',{'command':'uv run python -m unittest'}))
        self.assertFalse(role_allows('reviewer','run_command',{'command':'uv run python -m unittest'}))
        self.assertFalse(role_allows('tester','run_command',{'command':'npm test; del a.py'}))
        self.assertTrue(role_allows('tester','run_command',{'command':'npm --prefix frontend run typecheck'}))
        self.assertTrue(role_allows('tester','run_command',{'command':'npm --prefix frontend run typecheck && npm --prefix frontend test && npm --prefix frontend run build'}))
        self.assertFalse(role_allows('tester','run_command',{'command':'npm test && git push'}))
        self.assertFalse(role_allows('tester','run_command',{'command':'npm test && npm install'}))
        self.assertFalse(role_allows('tester','run_command',{'command':'npm --prefix ../../other test'}))
        self.assertFalse(role_allows('tester','run_command',{'command':'npm --prefix frontend install'}))
        command='uv run python -c "import missing_dependency"'
        self.assertFalse(role_allows('tester','run_command',{'command':command}))
        self.assertTrue(role_allows('tester','run_command',{'command':command},allowed_test_hashes=[hashlib.sha256(command.encode()).hexdigest()]))
        self.assertFalse(role_allows('tester','run_command',{'command':command+'; evil'},allowed_test_hashes=[hashlib.sha256(command.encode()).hexdigest()]))

    def test_resource_claims_serialize_conflicts(self):
        self.assertEqual(scheduling_conflict({'gui':True},{'gui':True}),'GUI_FOCUS_CONFLICT')
        self.assertEqual(scheduling_conflict({'workspace':'a'},{'workspace':'a'}),'SHARED_WORKTREE')
        self.assertIsNone(scheduling_conflict({'workspace':'a'},{'workspace':'b'}))

    def test_legacy_plan_semantics_and_idempotent_migration(self):
        pid=self.store.create('old','goal',[{'description':'first'},{'description':'second'}])
        first=self.store.active_step(pid)
        TaskPlanStore(self.db)
        self.assertEqual(first['id'],self.store.active_step(pid)['id'])
        self.assertEqual(first['workflow'],{})

    def test_templates_are_valid_data_and_parameters_do_not_grant_permission(self):
        templates=load_templates()
        self.assertEqual(len(templates),8)
        bug=expand_template('bugfix',{'goal':'修复加法','verification_command':'uv run python -m unittest'})
        self.assertEqual([s['assigned_role'] for s in bug['steps']],['planner','developer','reviewer','tester'])
        with self.assertRaises(ValueError):expand_template('bugfix',{'permission_mode':'full_access'})
        with self.assertRaises(ValueError):load_templates([templates[0]])

    def test_review_requires_fresh_evidence_and_repairs_preserve_completed_work(self):
        pid=self.store.create('t','goal',[
            {'task_id':'develop','description':'开发','dependencies':[]},
            {'task_id':'review','description':'审查','dependencies':['develop'],'assigned_role':'reviewer'}])
        dev,review=self.store.get(pid)['steps']
        self.store.record_execution(pid,dev['id'],'dev','turn','write_file',{'ok':True})
        self.store.update_step(pid,dev['id'],'completed',self.store.execution_evidence(pid,dev['id'],['dev']))
        with self.assertRaises(ValueError):self.store.review_workflow(pid,review['id'],'approved','没有读取')
        self.store.record_execution(pid,review['id'],'read1','turn','read_file',{'ok':True})
        self.store.review_workflow(pid,review['id'],'request_changes','缺少输入校验')
        repair=self.store.active_step(pid)
        self.assertEqual(repair['workflow']['assigned_role'],'developer')
        self.assertEqual(self.store.get(pid)['steps'][0]['state'],'completed')
        self.store.record_execution(pid,repair['id'],'repair','turn','write_file',{'ok':True})
        self.store.update_step(pid,repair['id'],'completed',self.store.execution_evidence(pid,repair['id'],['repair']))
        with self.assertRaises(ValueError):self.store.review_workflow(pid,review['id'],'approved','不能复用旧读取')
        self.store.record_execution(pid,review['id'],'read2','turn','read_file',{'ok':True})
        self.store.review_workflow(pid,review['id'],'approved','重新核实后通过')
        self.store.update_step(pid,review['id'],'completed',self.store.execution_evidence(pid,review['id'],['read2']))
        self.assertIsNone(self.store.active_step(pid))

    def test_background_restart_does_not_replay_or_resurrect_terminal_state(self):
        jobs=BackgroundJobs(self.db)
        jobs.add('one','thread','project');jobs.update('one','running')
        jobs.add('two','thread','project');jobs.update('two','cancelled')
        jobs=BackgroundJobs(self.db)
        states={j['id']:j['state'] for j in jobs.list()}
        self.assertEqual(states,{'one':'paused','two':'cancelled'})
        jobs.update('two','running')
        self.assertEqual(jobs.list()[0]['state'],'cancelled')


if __name__=='__main__':
    unittest.main()
