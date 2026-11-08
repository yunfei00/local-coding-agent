import asyncio
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import tempfile
import unittest
from unittest.mock import patch,AsyncMock

from agent.core.unified_runtime import infer_intent, verification_policy, result_view, workspace_snapshot,requested_intent,unreviewed_test_data
from agent.llm.router import validate_config
from agent.llm.base import ProviderChunk, ToolCall
from agent.server.main import AgentServer
from agent.task_plans import TaskPlanStore
from test_agent_reliability import FakeWebSocket, ScriptedProvider, final_step, tool_step


class UnifiedPolicyTests(unittest.TestCase):
    def test_literal_reference_check_never_rewrites_existing_files(self):
        from agent.core.unified_runtime import missing_file_references
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "pointer.txt").write_text("copied data", encoding="utf-8")
            goal = "Create pointer.txt containing index.csv."
            self.assertEqual(missing_file_references(root, goal, []),
                             [{"path": "pointer.txt", "literal_filename": "index.csv"}])
            self.assertEqual(missing_file_references(root, goal, ["pointer.txt"]), [])
            self.assertEqual(missing_file_references(root, "Create pointer.txt containing the contents of index.csv.", []), [])
            (root / "pointer.txt").write_text("index.csv\n", encoding="utf-8")
            self.assertEqual(missing_file_references(root, goal, []), [])

    def test_only_literal_relative_restore_targets_are_extracted(self):
        from agent.core.unified_runtime import initial_commit_restore_paths
        self.assertEqual(initial_commit_restore_paths(
            "Restore data/sample.csv from that commit, then restore ../secret from the commit."
        ), ["data/sample.csv"])
        self.assertEqual(initial_commit_restore_paths("Restore file.txt from HEAD~1"), [])

    def test_delivery_review_only_lists_new_nonedit_data(self):
        before = {"existing.json": [1, 1]}
        after = {path: [2, 2] for path in (
            "existing.json", "fixture.json", "export.csv", "package-lock.json", "app.py")}
        self.assertEqual(unreviewed_test_data(before, after, ["export.csv"]), ["fixture.json"])

    def test_request_shape_is_refined_by_tools_and_respects_read_only(self):
        self.assertEqual(requested_intent('Python 装饰器是什么？')['kind'],'question')
        self.assertEqual(requested_intent('请解释如何修改 Python 代码')['kind'],'question')
        self.assertEqual(requested_intent('把登录按钮文字改成中文')['kind'],'change')
        self.assertEqual(requested_intent('只返回 JSON，不读取或修改工程')['kind'],'question')
        self.assertTrue(requested_intent('只分析启动失败，不修改任何文件')['read_only'])
        self.assertFalse(requested_intent('Diagnose the failing assertion and repair mathbox.py, then run pytest again.')['read_only'])
        self.assertTrue(requested_intent('Only analyze why we need to repair mathbox.py.')['read_only'])
        self.assertTrue(requested_intent('Analyze repair options for mathbox.py.')['read_only'])
        for prompt in ('修复这个文件', '修改代码并运行测试', '诊断并修复错误',
                       'Diagnose and fix the file', 'Inspect and repair'):
            with self.subTest(prompt=prompt):
                self.assertFalse(requested_intent(prompt)['read_only'])
                self.assertEqual(requested_intent(prompt)['kind'], 'change')
        self.assertTrue(requested_intent('Inspect and repair. Do not modify any files.')['read_only'])
        self.assertEqual(requested_intent('实现以下要求\n1. 创建核心模块\n2. 编写测试\n3. 生成交付报告')['kind'],'complex')

    def test_chinese_edits_and_read_only_constraints(self):
        for goal in ("完善 cli.py 的错误处理", "追加一行，检查 Diff", "在 feature.txt 追加一行，再检查 diff", "替换标题", "删除过期条目"):
            self.assertEqual(requested_intent(goal)["kind"], "change")
        self.assertTrue(requested_intent("完善 CLI 的方案，只分析，不修改任何文件")["read_only"])

    def test_named_branch_contract_excludes_combined_edits(self):
        from agent.core.unified_runtime import requested_git_branch
        self.assertEqual(requested_git_branch("创建并切换到 fix/one 分支，保留文件。"), "fix/one")
        self.assertIsNone(requested_git_branch("创建并切换到 fix/one 分支，再修改代码。"))

    def test_local_output_can_be_unset_after_role_binding_change(self):
        self.assertIsNone(validate_config({"roles":{"executor":{"route":"api",
            "model_profile_id":"new-local", "output_limit":None}}})["roles"]["executor"]["output_limit"])
        with self.assertRaises(ValueError):
            validate_config({"roles":{"executor":{"route":"local","output_limit":0}}})

    def test_delivery_contract_requires_actual_artifact_and_command(self):
        from agent.core.verification import delivery_requirements, missing_deliverables
        contract = delivery_requirements("修复程序，提供 README.md，运行 python -m unittest -q。")
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            self.assertEqual(missing_deliverables(root, contract, []), ["README", "python -m unittest -q"])
            (root / "README.md").write_text("usage", encoding="utf-8")
            self.assertEqual(missing_deliverables(root, contract, [{"command":"python -m unittest -q","exit_code":0}]), [])

    def test_independent_verification_respects_user_contract_and_read_only(self):
        from agent.core.verification import workflow_verification_contract

        for goal in ('只分析持久化模块和单元测试，不修改文件。', '修改按钮的颜色。'):
            self.assertEqual(workflow_verification_contract(goal, requested_intent(goal)),
                             {'independent':False,'stateful':False})
        goal = '修复程序，运行 python -m unittest -q。'
        self.assertEqual(workflow_verification_contract(goal, requested_intent(goal)),
                         {'independent':True,'stateful':False})

    def test_explicit_preservation_requires_isolated_commands(self):
        from agent.core.verification import protected_workspace_files, protected_workspace_tool, protected_workspace_changes
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            protected = root / "VERSION"
            protected.write_text("original")
            frozen = protected_workspace_files(root, "修复版本读取。保持 VERSION 原样，不要初始化 Git。")
            self.assertEqual(set(frozen), {"VERSION"})
            self.assertIsNotNone(protected_workspace_tool(root, frozen, "delete_file", {"path":"VERSION"}))
            self.assertIsNotNone(protected_workspace_tool(root, frozen, "run_command", {"command":"python test_read.py"}))
            self.assertIsNone(protected_workspace_tool(root, frozen, "run_command",
                                                       {"command":"python test_read.py","isolated_cwd":True}))
            self.assertEqual(protected_workspace_changes(root, frozen), [])
            protected.unlink()
            self.assertEqual(protected_workspace_changes(root, frozen), ["VERSION"])

    def test_intent_uses_model_plan_and_actual_evidence_not_words(self):
        self.assertEqual(infer_intent('question','read_file',read_only=True),'analysis')
        self.assertEqual(infer_intent('analysis','write_file',changed_paths=['x.py']),'change')
        self.assertEqual(infer_intent('change','agent_plan'),'complex')
        self.assertEqual(infer_intent('change','write_file',changed_paths=['a','b','c']),'complex')
        self.assertEqual(infer_intent('complex','read_file'),'complex')

    def test_verification_levels_do_not_invent_test_tools(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);(root/'x.py').write_text('x=1')
            self.assertEqual(verification_policy(root,[])['level'],'none')
            self.assertEqual(verification_policy(root,['x.py'])['level'],'basic')
            self.assertEqual(verification_policy(root,['README.md'])['level'],'manual')
            self.assertEqual(verification_policy(root,['x.py'],override='none')['commands'],[])
            self.assertEqual(verification_policy(root,['x.py'],override='manual')['level'],'manual')
            (root/'package.json').write_text('{"scripts":{"typecheck":"tsc --noEmit","test":"vitest run"}}')
            self.assertEqual(verification_policy(root,['x.py'])['level'],'targeted')
            self.assertEqual(verification_policy(root,['x.py'],override='full')['level'],'full')

    def test_shell_path_encoding_does_not_interpolate_filenames(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);name="odd'$value.py";(root/name).write_text('x=1')
            command=verification_policy(root,[name])['commands'][0]
            self.assertNotIn(name,command)
            self.assertIn('base64.b64decode',command)

    def test_nested_package_paths_cannot_expand_shell_code(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);folder=root/'bad$(echo hidden)';folder.mkdir()
            (folder/'package.json').write_text('{"scripts":{"typecheck":"tsc --noEmit","test":"node test.js"}}')
            with self.assertRaises(ValueError):verification_policy(root,[folder.name+'/a.ts'])

    def test_typescript_without_type_checker_is_manual_not_a_false_pass(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);(root/'package.json').write_text('{"scripts":{"test":"node test.js"}}')
            result=verification_policy(root,['src/a.ts'])
            self.assertEqual(result['level'],'manual');self.assertEqual(result['commands'],[])
            self.assertIn('TypeScript',result['reason'])

    def test_package_discovery_resolves_root_alias_before_relative_paths(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);(root/'package.json').write_text('{"scripts":{"typecheck":"tsc --noEmit"}}')
            original=Path.cwd()
            try:
                os.chdir(root)
                result=verification_policy(Path('.'),['src/a.ts'])
            finally:
                os.chdir(original)
            self.assertIn('npm run typecheck',result['commands'])

    def test_result_cannot_trust_model_claims_or_diff_only(self):
        self.assertEqual(result_view(changed=True,results=[]),'completed_unverified')
        self.assertEqual(result_view(changed=True,results=[{'ok':False,'category':'environment'}]),'awaiting_user')
        self.assertEqual(result_view(changed=True,results=[{'ok':True}],pending=True),'partially_completed')
        self.assertEqual(result_view(changed=True,results=[{'ok':True}],level='targeted'),'completed_verified')
        self.assertEqual(result_view(changed=True,results=[],status='cancelled'),'cancelled')

    def test_upgrade_preserves_completed_steps_and_journal(self):
        db=sqlite3.connect(':memory:');store=TaskPlanStore(db)
        pid=store.create('t','goal',[{'description':'Original'}]);step=store.get(pid)['steps'][0]
        store.update_step(pid,step['id'],'completed',[{'tool':'write_file','ok':True}])
        store.append_steps(pid,[{'description':'New scope'}])
        self.assertEqual(store.get(pid)['steps'][0]['state'],'completed')
        self.assertEqual(store.get(pid)['steps'][0]['id'],step['id'])
        self.assertEqual(len(store.get(pid)['steps']),2)
        db.close()

    def test_snapshot_detects_shell_writes_and_deletes_not_dependencies(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);(root/'node_modules').mkdir();(root/'node_modules/a').write_text('ignored')
            (root/'x.py').write_text('a=1');before=workspace_snapshot(root)
            (root/'x.py').unlink();(root/'new.py').write_text('a=2')
            after=workspace_snapshot(root)
            self.assertIn('x.py',before);self.assertNotIn('x.py',after)
            self.assertIn('new.py',after);self.assertNotIn('node_modules/a',after)


class UnifiedLoopTests(unittest.IsolatedAsyncioTestCase):
    async def test_recreated_artifact_is_not_a_replay_of_its_prior_deletion(self):
        await self.run_steps([
            tool_step("write_file", {"path": "scratch-output.json", "content": "[1]"}),
            tool_step("delete_file", {"path": "scratch-output.json"}),
            tool_step("write_file", {"path": "scratch-output.json", "content": "[2]"}),
            tool_step("delete_file", {"path": "scratch-output.json"}),
            tool_step("write_file", {"path": "calculator.py", "content": "def add(a,b): return a+b\n"}),
            final_step("done"),
        ])
        deletions = [e["payload"]["result"] for e in self.ws.messages
                     if e["type"] == "tool.completed" and e["payload"]["name"] == "delete_file"]
        self.assertEqual([result["ok"] for result in deletions], [True, True])
        self.assertNotEqual(deletions[0]["data"]["recovery_id"], deletions[1]["data"]["recovery_id"])
        self.assertFalse((self.repo / "scratch-output.json").exists())

    async def test_git_exact_text_can_be_repaired_without_retrying_denied_operation(self):
        path = self.repo / "notes.txt"
        path.write_text("base\n", encoding="utf-8")
        subprocess.run(["git", "add", "--", path.name], cwd=self.repo, check=True)
        subprocess.run(["git", "-c", "user.name=Test", "-c", "user.email=test@example.invalid",
                        "commit", "-qm", "notes baseline"], cwd=self.repo, check=True)
        self.server.store.set_setting("orchestration.config", json.dumps(validate_config({
            "verification_commands": ["git diff --check"]})))
        self.server.approvals.request = AsyncMock(return_value="deny")
        provider = ScriptedProvider([
            tool_step("write_file", {"path": path.name, "content": "base\n MARKER\n"}),
            tool_step("git_commit", {"message": "unauthorized attempt"}),
            final_step("done"),
            tool_step("write_file", {"path": path.name, "content": "base\nMARKER\n"}),
            final_step("done"),
        ])
        await self.server.run_tool_turn(
            self.ws, thread_id=self.thread.id, turn_id="literal-repair", model="mock", provider=provider,
            prompt="Fix notes.txt and run tests. Use Git branch status. Append MARKER to notes.txt. Leave notes.txt uncommitted.", unified=True)
        self.assertEqual(path.read_text(), "base\nMARKER\n")
        results = [e["payload"] for e in self.ws.messages if e["type"] == "tool.completed"]
        denied = [e for e in results if e["name"] == "git_commit"]
        self.assertEqual(len(denied), 1)
        self.assertFalse(denied[0]["result"]["ok"])
        self.assertEqual(sum(e["name"] == "write_file" and e["result"]["ok"] for e in results), 2)

    async def test_unexpected_turn_error_sends_terminal_event_without_sensitive_message(self):
        with patch.object(self.server, "run_tool_turn", AsyncMock(side_effect=ValueError("private fixture text"))):
            self.server.ensure_model_available = AsyncMock(return_value=True)
            await self.server.handle_message(self.ws, {
                "type": "turn.start", "thread_id": self.thread.id,
                "payload": {"model": "mock", "prompt": "检查项目", "unified": True},
            }, set())
            await asyncio.gather(*list(self.server.active_turns.values()))
        terminal = [event for event in self.ws.messages if event["type"] == "turn.failed"]
        self.assertEqual(terminal[-1]["payload"]["code"], "AGENT_INTERNAL_ERROR")
        self.assertNotIn("private fixture text", repr(terminal))

    async def test_same_file_replacement_resolves_a_stale_patch(self):
        _, runtime = await self.run_steps([
            tool_step("apply_patch", {"path": "calculator.py", "old_text": "not present", "new_text": "ignored"}),
            tool_step("write_file", {"path": "calculator.py", "content": "def add(a, b): return a+b\n"}),
            final_step("实现完成"),
        ])
        self.assertEqual(runtime["outcome"], "completed_verified")
        results = [event["payload"]["result"] for event in self.ws.messages if event["type"] == "tool.completed"]
        self.assertEqual(results[0]["error"]["code"], "PATCH_NOT_FOUND")
        self.assertTrue(results[1]["ok"])

    async def test_unrelated_write_does_not_resolve_a_stale_patch(self):
        (self.repo / "calculator.py").write_text("def add(a, b): return a+b\n", encoding="utf-8")
        await self.run_steps([
            tool_step("apply_patch", {"path": "calculator.py", "old_text": "not present", "new_text": "ignored"}),
            tool_step("write_file", {"path": "other.py", "content": "ready = True\n"}),
            final_step("实现完成"),
            final_step("实现完成"),
        ])
        failures = [event["payload"]["code"] for event in self.ws.messages if event["type"] == "turn.failed"]
        self.assertEqual(failures, ["PLAN_TOOLS_UNRESOLVED"])

    async def asyncSetUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name);self.repo=self.root/'repo';self.repo.mkdir()
        self.env=patch.dict(os.environ,{'LCA_DATA_DIR':str(self.root/'data')});self.env.start()
        (self.repo/'calculator.py').write_text('def add(a,b): return a-b\n')
        (self.repo/'tests').mkdir();(self.repo/'tests/test_calc.py').write_text('import unittest\nfrom calculator import add\nclass Calc(unittest.TestCase):\n def test_add(self): self.assertEqual(add(3,2),5)\n')
        (self.repo/'.gitignore').write_text('__pycache__/\n.venv/\n')
        for args in (['init','-q'],['config','user.name','Test'],['config','user.email','test@example.test'],['add','.'],['commit','-qm','fixture']):
            subprocess.run(['git',*args],cwd=self.repo,capture_output=True,check=True)
        self.server=AgentServer('test');self.project,self.thread,_=self.server.projects.open(str(self.repo),active_model='test')
        self.ws=FakeWebSocket()
        async def approve(*a,**kw):return 'allow_once'
        self.server.approvals.request=approve
        self.server.store.set_setting('orchestration.config',json.dumps(validate_config({'verification_commands':['uv run --no-project python -m unittest discover -s tests -v']})))

    async def asyncTearDown(self):
        await self.server.close_async();self.server.close();self.env.stop();self.temp.cleanup()

    async def run_steps(self,steps,prompt='按照实际需求完成工作'):
        provider=ScriptedProvider(steps)
        try:
            await self.server.run_tool_turn(self.ws,thread_id=self.thread.id,turn_id='unified-test',prompt=prompt,model='mock',provider=provider,unified=True)
        except asyncio.CancelledError:
            if not getattr(self, 'observed_test_boundary', False):
                raise
        updates=[x['payload']['runtime'] for x in self.ws.messages if x['type']=='agent.runtime.updated']
        return provider,updates[-1]

    def stop_after_events(self, event_type, count):
        send = self.ws.send_json

        async def observe(event):
            await send(event)
            if event['type'] == event_type and sum(row['type'] == event_type for row in self.ws.messages) >= count:
                self.observed_test_boundary = True
                self.server.cancelling_turns.add('unified-test')

        self.ws.send_json = observe

    async def test_stateful_plan_requires_independent_tester(self):
        nodes = [{'task_id':f'work-{i}', 'description':f'实现阶段 {i}', 'assigned_role':'developer'}
                 for i in range(4)]
        self.server.store.set_setting('orchestration.config',json.dumps(validate_config({})))
        self.stop_after_events('plan.loaded', 1)
        provider, _ = await self.run_steps([
            tool_step('agent_plan', {'steps':nodes}), tool_step('agent_plan', {'steps':nodes}),
        ], '实现跨进程持久化工具，提供 unittest 功能测试。')
        plans = [event['payload']['plans'][0] for event in self.ws.messages if event['type']=='plan.loaded']
        self.assertTrue(plans)
        tester = plans[0]['steps'][-1]['workflow']
        self.assertEqual(tester['assigned_role'], 'tester')
        self.assertEqual(tester['source'], 'runtime_independent_verification')
        self.assertEqual(set(tester['dependencies']), {f'work-{i}' for i in range(4)})
        self.assertEqual(provider.calls, 2)

    async def test_required_tester_executes_before_final_verification(self):
        self.server.store.set_setting('orchestration.config',json.dumps(validate_config({})))
        nodes = [
            {'task_id':'build','description':'修复计算模块','assigned_role':'developer'},
            {'task_id':'docs','description':'写交付文档','assigned_role':'developer'},
            {'description':'独立测试','assigned_role':'tester','dependencies':['build'],'verification':'运行真实测试'},
        ]
        _, result = await self.run_steps([
            tool_step('agent_plan', {'steps':nodes}), tool_step('agent_plan', {'steps':nodes}),
            tool_step('write_file', {'path':'calculator.py','content':'def add(a,b): return a+b\n'}),
            final_step('实现完成'),
            tool_step('write_file', {'path':'README.md','content':'运行 python -m unittest discover -s tests -v\n'}),
            final_step('文档完成'),
            tool_step('write_file', {'path':'calculator.py','content':'must not write'}),
            tool_step('run_command', {'command':'python -m unittest discover -s tests -v'}),
            final_step('独立功能测试通过'),
        ], '修复持久化程序，提供 unittest 功能测试。')
        self.assertEqual(result['outcome'], 'completed_verified', str(result))
        self.assertEqual([row['role'] for row in result['role_handoffs']], ['developer','developer','tester'])
        self.assertEqual(result['test_handoff']['status'], 'PASS')
        self.assertEqual((self.repo / 'calculator.py').read_text(), 'def add(a,b): return a+b\n')

    async def test_developer_stateful_commands_share_only_scratch_data(self):
        state = self.repo / 'records.json'
        state.write_text('{"original":true}', encoding='utf-8')
        commands = [
            """python -c "import json; from pathlib import Path; Path('records.json').write_text(json.dumps({'record': 2}))" """,
            """python -c "import json; from pathlib import Path; p=Path('records.json'); v=json.loads(p.read_text()); assert v['record']==2; v['record']+=3; p.write_text(json.dumps(v))" """,
            """python -c "import json,sys; from pathlib import Path; assert json.loads(Path('records.json').read_text())=={'record':5}; sys.exit(2)" """,
            """python -c "import json; from pathlib import Path; assert json.loads(Path('records.json').read_text())=={'record':5}" """,
        ]
        self.stop_after_events('tool.completed', len(commands))
        await self.run_steps([tool_step('run_command', {'command':command.strip(), **({'expected_exit_codes':[2]} if i==2 else {})})
                              for i,command in enumerate(commands)], '实现带持久化的记录程序，提供 unittest 功能测试。')
        self.assertEqual(state.read_text(encoding='utf-8'), '{"original":true}')
        results = [event['payload']['result'] for event in self.ws.messages
                   if event['type']=='tool.completed' and not event['payload'].get('independent_verification')]
        self.assertEqual([r['exit_code'] for r in results], [0, 0, 2, 0])
        self.assertTrue(all(r['ok'] and r['data']['command_outcome']['isolated'] for r in results))

    async def test_stateful_python_child_cannot_write_absolute_delivery_path(self):
        import base64
        import shlex

        state = self.repo / 'retained.json'
        state.write_text('original', encoding='utf-8')
        encoded = base64.b64encode(str(state).encode()).decode()
        child = f"import base64,pathlib; pathlib.Path(base64.b64decode('{encoded}').decode()).write_text('changed')"
        normal = "import pathlib; pathlib.Path('scratch-child.txt').write_text('child ok')"
        commands = [
            f'import subprocess,sys; subprocess.run([sys.executable, "-c", {normal!r}],check=True)',
            f'import subprocess,sys; subprocess.run([sys.executable, "-c", {child!r}],capture_output=True)',
        ]
        self.stop_after_events('tool.completed', len(commands))
        await self.run_steps([tool_step('run_command', {'command':'python -c '+shlex.quote(code)}) for code in commands],
                             '实现带持久化的记录程序，提供 unittest 功能测试。')
        results = [event['payload']['result'] for event in self.ws.messages if event['type']=='tool.completed']
        self.assertTrue(results[0]['ok'], str(results[0]))
        self.assertFalse(results[1]['ok'], str(results[1]))
        self.assertEqual(results[1]['data']['error_code'], 'VERIFICATION_ISOLATION_PERMISSION')
        self.assertEqual(state.read_text(encoding='utf-8'), 'original')
        self.assertFalse((self.repo / 'scratch-child.txt').exists())

    async def test_truncated_batch_retries_without_dispatching_buffered_calls(self):
        self.server.model_retry_attempts = 2
        provider = ScriptedProvider([
            tool_step("read_file", {"path": "calculator.py"}),
            ProviderChunk(content="partial", done=True, finish_reason="length",
                          tool_calls=(ToolCall("write_file", {"path": "discard.txt", "content": "bad"}),)),
            final_step("读取完成"),
        ])
        await self.server.run_tool_turn(self.ws, thread_id=self.thread.id, turn_id="truncated-test",
            prompt="检查当前工程的计算器", model="mock", provider=provider, unified=True)
        self.assertEqual(provider.calls, 3)
        self.assertFalse((self.repo / "discard.txt").exists())
        completed = [e["payload"]["name"] for e in self.ws.messages if e["type"] == "tool.completed"]
        self.assertEqual(completed, ["read_file"])
        retry = next(e["payload"] for e in self.ws.messages
                     if e["type"] == "turn.status" and e["payload"].get("phase") == "tool_protocol_retry")
        self.assertEqual(retry["discarded_tool_calls"], 1)
        events = self.server.runtime_ledger.events(run_id="truncated-test")
        failures = [e for e in events if e["kind"] == "request.failed"]
        self.assertEqual(len(failures), 1)
        self.assertEqual(failures[0]["metadata"]["failure_class"], "OUTPUT_TRUNCATED")

    async def test_workflow_roles_use_same_loop_and_actual_evidence(self):
        nodes=[
            {'task_id':'fix','description':'修复计算器','assigned_role':'developer','dependencies':[]},
            {'task_id':'review','description':'独立重新读取代码审查','assigned_role':'reviewer','dependencies':['fix']},
            {'task_id':'test','description':'运行单元测试','assigned_role':'tester','dependencies':['review'],'verification':'uv run --no-project python -m unittest discover -s tests -v'},
        ]
        _,r=await self.run_steps([
            tool_step('agent_plan',{'steps':nodes}),
            tool_step('write_file',{'path':'calculator.py','content':'def add(a,b): return a+b\n'}),final_step('实现完成'),
            tool_step('read_file',{'path':'calculator.py'}),tool_step('workflow_review',{'decision':'approved','summary':'重新读取后确认加法正确'}),final_step('独立审查通过'),
            tool_step('write_file',{'path':'calculator.py','content':'tester must never write'}),
            tool_step('run_command',{'command':'uv run --no-project python -m unittest discover -s tests -v'}),final_step('测试通过，中文交付'),
        ])
        self.assertEqual(r['outcome'],'completed_verified')
        self.assertEqual(r['workflow_progress']['completed'],3)
        self.assertEqual([h['role'] for h in r['role_handoffs']],['developer','reviewer','tester'])
        plan=self.server.store.task_plans.get(r['plan_id'])
        self.assertTrue(all(s['state']=='completed' and s['executions'] for s in plan['steps']))
        self.assertIn('a+b',(self.repo/'calculator.py').read_text())
        delivery=json.loads(Path(r['delivery']['json_path']).read_text(encoding='utf-8'))
        self.assertEqual(delivery['status'],'已完成且验证通过')
        self.assertEqual(len(delivery['steps']),3)
        self.assertEqual(delivery['reviews'][-1]['decision'],'approved')

    async def test_missing_test_hands_back_to_developer_before_tester(self):
        (self.repo / 'tests' / 'test_calc.py').unlink()
        self.server.store.set_setting('orchestration.config',json.dumps(validate_config({})))
        fixture = self.repo / "validation-state.json"
        fixture.write_text('{"original":true}', encoding='utf-8')
        command = "python -m unittest discover -s . -p test_delivery.py -v"
        _, result = await self.run_steps([
            tool_step('agent_plan', {'steps':[
                {'task_id':'build','description':'修复计算器','assigned_role':'developer','dependencies':[]},
                {'task_id':'verify','description':'验证交付','assigned_role':'tester','dependencies':['build'],
                 'verification':'运行真实测试'},
            ]}),
            tool_step('write_file', {'path':'calculator.py','content':'def add(a,b): return a+b\n'}),
            final_step('实现完成'),
            tool_step('write_file', {'path':'test_delivery.py','content':
                'import unittest\nfrom pathlib import Path\nfrom calculator import add\nclass Check(unittest.TestCase):\n'
                ' def test_add(self):\n'
                '  state = Path("validation-state.json")\n'
                '  state.write_text(str(add(2,3)))\n'
                '  self.assertEqual(state.read_text(), "5")\n'}),
            tool_step('workflow_test_handoff', {'script':'test_delivery.py','command':command,
                'cwd':'.','expected_exit_codes':[0],'isolated_cwd':True}),
            final_step('已声明隔离验收'),
            tool_step('run_command', {'command':command,'isolated_cwd':True,'expected_exit_codes':[0]}),
            final_step('真实测试通过'),
        ])
        self.assertEqual(result['outcome'], 'completed_verified', str(result))
        self.assertEqual([row['role'] for row in result['role_handoffs']], ['developer','developer','tester'])
        plan = self.server.store.task_plans.get(result['plan_id'])
        tester = next(step for step in plan['steps'] if step['workflow']['assigned_role']=='tester')
        self.assertEqual(tester['state'], 'completed')
        self.assertTrue(any(row['tool']=='run_command' and row['exit_code']==0 for row in tester['executions']))
        self.assertEqual(result['test_handoff']['status'], 'PASS')
        self.assertEqual(fixture.read_text(encoding='utf-8'), '{"original":true}')
        commands = [row for row in tester['executions'] if row['tool']=='run_command']
        self.assertTrue(any(row['metadata'].get('command_outcome',{}).get('isolated') is True for row in commands))

    async def test_reviewer_cannot_write_even_if_provider_forges_hidden_tool(self):
        _,r=await self.run_steps([
            tool_step('agent_plan',{'steps':[{'task_id':'review','description':'审查','assigned_role':'reviewer','dependencies':[]}]}),
            tool_step('write_file',{'path':'calculator.py','content':'tampered'}),
        ])
        self.assertEqual(r['error_code'],'WORKFLOW_ROLE_PERMISSION')
        self.assertIn('a-b',(self.repo/'calculator.py').read_text())

    async def test_four_roles_use_independent_models_and_frozen_bindings(self):
        developer=ScriptedProvider([
            tool_step('workflow_template',{'template_id':'bugfix'}),
            tool_step('write_file',{'path':'calculator.py','content':'def add(a,b): return a+b\n'}),final_step('开发完成')])
        planner=ScriptedProvider([tool_step('read_file',{'path':'calculator.py'}),final_step('根因是减法')])
        reviewer=ScriptedProvider([tool_step('read_file',{'path':'calculator.py'}),tool_step('workflow_review',{'decision':'approved','summary':'重新读取后通过'}),final_step('审查完成')])
        tester=ScriptedProvider([tool_step('run_command',{'command':'uv run --no-project python -m unittest discover -s tests -v'}),final_step('真实测试通过')])
        clients={'planner':planner,'reviewer':reviewer,'tester':tester}
        for pid,client in clients.items():
            client.agent_tools_enabled=True
            client.profile_snapshot={'profile':{'model_profile_id':pid},'request_seconds':60}
        self.server.store.set_setting('workflow.config',json.dumps({'role_models':{r:r for r in clients}}))
        def resolve(selection,snapshot=None):
            pid=selection.removeprefix('profile:')
            return clients[pid],pid+'-model'
        with patch.object(self.server,'chat_provider',side_effect=resolve):
            await self.server.run_tool_turn(self.ws,thread_id=self.thread.id,turn_id='four-roles',prompt='请修复 calculator.py 并审查和测试',model='developer-model',provider=developer,unified=True)
        r=[e['payload']['runtime'] for e in self.ws.messages if e['type']=='agent.runtime.updated'][-1]
        self.assertEqual(r['outcome'],'completed_verified')
        self.assertEqual([h['role'] for h in r['role_handoffs']],['planner','developer','reviewer','tester'])
        self.assertEqual([h['model'] for h in r['role_handoffs']],['planner-model','developer-model','reviewer-model','tester-model'])
        self.assertTrue(all(c.calls for c in clients.values()))

    async def test_question_has_no_plan_or_tools(self):
        p,r=await self.run_steps([final_step('装饰器包装函数以增加行为')])
        self.assertEqual(p.calls,1);self.assertEqual(r['intent'],'question')
        self.assertEqual(self.server.store.task_plans.list_for_thread(self.thread.id),[])
        self.assertEqual(r['verification'],[])

    async def test_prose_only_development_cannot_complete_or_loop_forever(self):
        p=ScriptedProvider([final_step('这里是代码示例'),final_step('仍然只有示例')])
        await self.server.run_tool_turn(self.ws,thread_id=self.thread.id,turn_id='prose-only',prompt='请实现真实的代码修改',model='mock',provider=p,unified=True)
        self.assertEqual(p.calls,2)
        self.assertTrue(any(e['type']=='turn.failed' and e['payload'].get('code')=='AGENT_NO_CHANGE_EVIDENCE' for e in self.ws.messages))
        self.assertIn('a-b',(self.repo/'calculator.py').read_text())

    async def test_read_only_user_intent_blocks_model_mutation(self):
        p=ScriptedProvider([tool_step('write_file',{'path':'calculator.py','content':'wrong'})])
        await self.server.run_tool_turn(self.ws,thread_id=self.thread.id,turn_id='read-only-request',prompt='只分析程序，不修改任何文件',model='mock',provider=p,unified=True)
        self.assertIn('a-b',(self.repo/'calculator.py').read_text())
        self.assertTrue(any(e['type']=='turn.failed' and e['payload'].get('code')=='UNIFIED_READ_ONLY_INTENT' for e in self.ws.messages))

    async def test_concept_question_exposes_no_tools_and_rejects_invented_tool_calls(self):
        class QuestionProvider(ScriptedProvider):
            async def stream_chat(self,**kwargs):
                self_outer.assertIsNone(kwargs.get('tools'))
                async for chunk in super().stream_chat(**kwargs):yield chunk
        self_outer=self
        p=QuestionProvider([tool_step('write_file',{'path':'calculator.py','content':'bad'})])
        await self.server.run_tool_turn(self.ws,thread_id=self.thread.id,turn_id='concept-question',prompt='请解释 Python 装饰器',model='mock',provider=p,unified=True)
        self.assertIn('a-b',(self.repo/'calculator.py').read_text())
        self.assertEqual(self.server.store.task_plans.list_for_thread(self.thread.id),[])
        self.assertTrue(any(e['type']=='turn.failed' and e['payload'].get('code')=='UNIFIED_QUESTION_TOOLS' for e in self.ws.messages))

    async def test_read_only_analysis_has_no_development_plan(self):
        _,r=await self.run_steps([tool_step('read_file',{'path':'calculator.py'}),final_step('减法导致错误')])
        self.assertEqual(r['intent'],'analysis');self.assertEqual(r['changed_paths'],[])

    async def test_read_only_failed_test_is_diagnostic_evidence_not_failed_development(self):
        p=ScriptedProvider([tool_step('read_file',{'path':'calculator.py'}),
            tool_step('run_command',{'command':'uv run --no-project python -m unittest discover -s tests -v'}),
            final_step('真实测试退出 1，3-2 得到 1，程序使用减法导致断言失败；未修改文件。')])
        await self.server.run_tool_turn(self.ws,thread_id=self.thread.id,turn_id='analysis-failure',prompt='分析 calculator.py 为什么失败；只分析，不修改任何文件',model='mock',provider=p,unified=True)
        r=[x['payload']['runtime'] for x in self.ws.messages if x['type']=='agent.runtime.updated'][-1]
        self.assertEqual(r['phase'],'completed');self.assertEqual(r['intent'],'analysis')
        self.assertEqual(r['diagnostic_checks'][0]['exit_code'],1)
        self.assertEqual(r['verification'],[]);self.assertEqual(r['changed_paths'],[])
        self.assertEqual(self.server.store.task_plans.list_for_thread(self.thread.id),[])
        self.assertFalse(any(e['type']=='turn.failed' for e in self.ws.messages))
        self.assertEqual(self.server.store.task_plans.list_for_thread(self.thread.id),[])

    async def test_edit_automatically_runs_real_unittest_and_diff_without_model_command(self):
        p,r=await self.run_steps([tool_step('write_file',{'path':'calculator.py','content':'def add(a,b): return a+b\n'}),final_step('已修改')])
        self.assertEqual(p.calls,2);self.assertEqual(r['outcome'],'completed_verified')
        self.assertTrue(r['verification'][0]['ok']);self.assertIn('Ran 1 test',r['verification'][0]['summary'])
        self.assertTrue(Path(r['verification'][0]['log_path']).is_file())
        self.assertIn('calculator.py',r['changed_paths'])

    async def test_real_failed_independent_test_is_repaired_then_verified(self):
        p,r=await self.run_steps([tool_step('write_file',{'path':'calculator.py','content':'def add(a,b): return a*b\n'}),final_step('声称通过不是证据'),tool_step('write_file',{'path':'calculator.py','content':'def add(a,b): return a+b\n'}),final_step('修复完成')])
        self.assertEqual(p.calls,4);self.assertEqual(r['repairs'],1);self.assertEqual(r['outcome'],'completed_verified')
        self.assertTrue(any(x['payload']['runtime']['phase']=='repairing' for x in self.ws.messages if x['type']=='agent.runtime.updated'))

    async def test_missing_dependency_stops_without_another_model_request(self):
        self.server.store.set_setting('orchestration.config',json.dumps(validate_config({'verification_commands':['uv run --no-project python -c "import lca_missing_dependency_01234"']})))
        p,r=await self.run_steps([tool_step('write_file',{'path':'calculator.py','content':'def add(a,b): return a+b\n'}),final_step('完成')])
        self.assertEqual(p.calls,2);self.assertEqual(r['outcome'],'awaiting_user')
        self.assertEqual(r['verification'][0]['category'],'environment')
        self.assertEqual(r['verification'][0]['exit_code'],1)

    async def test_explicit_none_finishes_unverified_without_false_pass_or_block(self):
        self.server.store.set_setting('orchestration.config',json.dumps(validate_config({'verification_level':'none'})))
        _,r=await self.run_steps([tool_step('write_file',{'path':'calculator.py','content':'def add(a,b): return a+b\n'}),final_step('修改完成，未运行测试')])
        self.assertEqual(r['phase'],'completed');self.assertEqual(r['outcome'],'completed_unverified')
        self.assertEqual(r['verification'],[]);self.assertFalse(r['validation_blocked'])

    async def test_request_timeout_is_not_reported_as_total_task_timeout(self):
        class SlowProvider(ScriptedProvider):
            request_timeout=.02
            async def stream_chat(self,**kwargs):
                self.calls+=1
                self.response_metadata={'http_status':200,'request_sent':True,'stream_events':8,'tool_argument_chars':600,'reasoning_chars':250,'response_complete':False}
                await asyncio.sleep(1)
                if False:yield
        p=SlowProvider([])
        await self.server.run_tool_turn(self.ws,thread_id=self.thread.id,turn_id='request-timeout',prompt='解释装饰器',model='mock',provider=p,unified=True)
        errors=[e['payload'] for e in self.ws.messages if e['type']=='turn.failed']
        self.assertEqual(p.calls,1);self.assertEqual(errors[-1]['code'],'MODEL_REQUEST_TIMEOUT')
        data=json.loads(self.server.store.connection.execute('SELECT data_json FROM agent_execution_runs WHERE id=?',('request-timeout',)).fetchone()[0])
        self.assertEqual(data['unified_api_requests'][0]['status'],'failed')
        self.assertGreater(data['unified_api_requests'][0]['reserved_tokens'],0)
        self.assertEqual(data['unified_api_requests'][0]['tool_argument_chars'],600)

    async def test_invalid_tool_response_keeps_reported_cache_cost_and_idempotent_usage(self):
        from agent.core.execution import ExecutionBudget
        budget=ExecutionBudget(self.server.store.connection,'usage-only',self.thread.id,self.server.continuation_policy)
        identifier=budget.reserve([],None,20,api_budget=self.server.tasks.settings()['budget'],runtime=self.server.tasks.runtime)
        budget.finish_api(identifier,status='failed',metadata={'response_complete':True,'reported_usage':{
            'input_tokens':10,'output_tokens':4,'cached_tokens':6,'actual_cost':.003}})
        budget.finish_api(identifier,status='failed',metadata={'response_complete':True,'reported_usage':{
            'input_tokens':999,'output_tokens':999,'cached_tokens':999,'actual_cost':999}})
        usage=self.server.tasks.runtime.usage('usage-only')
        self.assertEqual(usage['api_calls'],1);self.assertEqual(usage['reserved_tokens'],14)
        self.assertEqual(usage['cached_tokens'],6);self.assertAlmostEqual(usage['actual_cost'],.003)
        self.assertFalse(usage['estimated']);self.assertTrue(usage['actual_cost_known'])

    async def test_explicit_zero_budget_sends_no_request(self):
        self.server.store.set_setting('orchestration.config',json.dumps(validate_config({'budget':{'api_calls':0}})))
        p,r=await self.run_steps([final_step('must not be called')])
        self.assertEqual(p.calls,0);self.assertEqual(r['phase'],'failed')

    async def test_complex_model_plan_persists_and_completes_using_real_evidence(self):
        _,r=await self.run_steps([tool_step('agent_plan',{'steps':[{'description':'Inspect and fix'}]}),tool_step('read_file',{'path':'calculator.py'}),tool_step('write_file',{'path':'calculator.py','content':'def add(a,b): return a+b\n'}),final_step('交付完成')])
        self.assertEqual(r['intent'],'complex');self.assertEqual(r['outcome'],'completed_verified')
        plan=self.server.store.task_plans.get(r['plan_id'])
        self.assertEqual(plan['steps'][0]['state'],'completed')
        self.assertGreater(len(self.server.store.task_plans.executions(r['plan_id'])),0)
        self.assertNotIn('execution',r['plan'])
        self.assertLess(len(json.dumps(plan['execution'])),100000)

    async def test_missing_step_evidence_gets_one_correction_not_false_completion(self):
        p,r=await self.run_steps([tool_step('agent_plan',{'steps':[{'description':'Repair calculator'},{'description':'Inspect intermediate implementation','verification':'A successful command'},{'description':'Review final implementation'}]}),
            tool_step('write_file',{'path':'calculator.py','content':'def add(a,b): return a+b\n'}),final_step('第一步完成'),
            final_step('只描述已完成的事情'),
            tool_step('run_command',{'command':'uv run --no-project python -m unittest discover -s tests -v'}),final_step('已实际验证'),
            tool_step('read_file',{'path':'calculator.py'}),final_step('已核对并交付')])
        self.assertEqual(r['phase'],'completed');self.assertEqual(r['outcome'],'completed_verified')
        self.assertTrue(all(s['state']=='completed' for s in r['plan']['steps']))
        self.assertEqual(p.calls,8)

    async def test_missing_step_evidence_stops_after_bounded_correction(self):
        p,r=await self.run_steps([tool_step('agent_plan',{'steps':[{'description':'Inspect the source'}]}),final_step('没有工具'),final_step('仍然没有工具')])
        self.assertEqual(p.calls,3);self.assertEqual(r['phase'],'failed')
        self.assertTrue(any(e['type']=='turn.failed' and e['payload'].get('code')=='PLAN_STEP_NO_EVIDENCE' for e in self.ws.messages))

    async def test_restart_snapshot_api_returns_real_persisted_result(self):
        _,r=await self.run_steps([final_step('回答')])
        ws=FakeWebSocket()
        await self.server.tasks.handle(ws,{'type':'task.runtime.list','thread_id':self.thread.id,'payload':{}},set())
        self.assertEqual(ws.messages[-1]['payload']['runtimes'][0]['id'],r['id'])

    async def test_bad_project_verification_config_is_specific_unverified_result(self):
        self.server.store.set_setting('orchestration.config',json.dumps(validate_config({})))
        (self.repo/'.lca').mkdir();(self.repo/'.lca/verification.json').write_text('invalid json')
        p,r=await self.run_steps([tool_step('write_file',{'path':'calculator.py','content':'def add(a,b): return a+b\n'}),final_step('完成')])
        self.assertEqual(p.calls,2);self.assertEqual(r['outcome'],'awaiting_user')
        self.assertEqual(r['verification'][0]['category'],'configuration')

    async def test_api_cost_cap_without_prices_prevents_first_request(self):
        self.server.store.set_setting('orchestration.config',json.dumps(validate_config({'budget':{'api_cost':1}})))
        p,r=await self.run_steps([final_step('must not run')])
        self.assertEqual(p.calls,0);self.assertIn('prices',r['reason'])

    async def test_unified_requests_count_toward_original_global_budget(self):
        p,r=await self.run_steps([final_step('回答')])
        self.assertEqual(self.server.tasks.runtime.usage()['api_calls'],1)
        from agent.core.budget import BudgetGuard,BudgetExceeded
        task=self.server.tasks.runtime.create(self.thread.id,'Legacy task',validate_config({}),'workspace')
        guard=BudgetGuard(self.server.tasks.runtime,task['id'],validate_config({'budget':{'global_api_calls':1}})['budget'])
        with self.assertRaises(BudgetExceeded):
            guard.reserve(route='api',role='executor',model='mock',messages=[{'role':'user','content':'goal'}],tools=None,context_window=65536,output_limit=100)

    async def test_cancellation_and_resume_keep_budget_baseline_and_completed_effects(self):
        class EditThenBlock(ScriptedProvider):
            def __init__(self):
                super().__init__([tool_step('write_file',{'path':'calculator.py','content':'def add(a,b): return a+b\n'})]);self.waiting=asyncio.Event()
            async def stream_chat(self,**kwargs):
                if self.calls==0:
                    async for chunk in super().stream_chat(**kwargs):yield chunk
                else:
                    self.waiting.set();await asyncio.sleep(30)
        p=EditThenBlock()
        turn=asyncio.create_task(self.server.run_tool_turn(self.ws,thread_id=self.thread.id,turn_id='interrupt',prompt='Fix addition',model='mock',provider=p,unified=True))
        await asyncio.wait_for(p.waiting.wait(),10);turn.cancel()
        with self.assertRaises(asyncio.CancelledError):await turn
        plan=self.server.store.task_plans.list_for_thread(self.thread.id)[0]
        original=[x for x in self.server.store.task_plans.executions(plan['id']) if x['tool']=='write_file' and x['status']=='succeeded']
        before=self.server.tasks.runtime.usage()['api_calls']
        self.server.store.set_setting('orchestration.config',json.dumps(validate_config({'budget':{'api_calls':0}})))
        await self.server.handle_message(self.ws,{'type':'plan.recover','thread_id':self.thread.id,'payload':{'plan_id':plan['id']}},set())
        provider=ScriptedProvider([tool_step('read_file',{'path':'calculator.py'}),final_step('已检查原修改并验证')])
        self.server.provider=provider;self.server.ensure_model_available=AsyncMock(return_value=True)
        await self.server.handle_message(self.ws,{'type':'turn.start','thread_id':self.thread.id,'payload':{'prompt':'恢复原任务','model':'mock','unified':True}},set())
        await asyncio.gather(*self.server.active_turns.values())
        r=[x['payload']['runtime'] for x in self.ws.messages if x['type']=='agent.runtime.updated'][-1]
        self.assertEqual(provider.calls,2)
        self.assertEqual(r['outcome'],'completed_verified')
        self.assertEqual(r['plan_id'],plan['id'])
        self.assertEqual([x for x in self.server.store.task_plans.executions(plan['id']) if x['tool']=='write_file' and x['status']=='succeeded'],original)
        self.assertEqual(self.server.tasks.runtime.usage()['api_calls'],before+2)

    async def test_three_file_scope_upgrades_with_existing_evidence(self):
        _,r=await self.run_steps([tool_step('write_file',{'path':'calculator.py','content':'def add(a,b): return a+b\n'}),tool_step('write_file',{'path':'a.py','content':'a=1\n'}),tool_step('write_file',{'path':'b.py','content':'b=2\n'}),final_step('完成')])
        self.assertEqual(r['intent'],'complex');self.assertEqual(r['outcome'],'completed_verified')
        self.assertEqual(len([x for x in self.server.store.task_plans.executions(r['plan_id']) if x['tool']=='write_file']),3)

    async def test_paused_plan_does_not_block_question_or_allow_unconfirmed_mutation(self):
        pid=self.server.store.task_plans.create(self.thread.id,'Original goal',[{'description':'Pending change'}])
        step=self.server.store.task_plans.get(pid)['steps'][0]
        self.server.store.task_plans.update_step(pid,step['id'],'in_progress')
        self.server.store.task_plans.update_step(pid,step['id'],'blocked')
        provider=ScriptedProvider([final_step('装饰器解释')])
        await self.server.run_tool_turn(self.ws,thread_id=self.thread.id,turn_id='question-while-blocked',prompt='解释装饰器',model='mock',provider=provider,unified=True,deferred_plan_ids=[pid])
        self.assertEqual(self.server.store.task_plans.get(pid)['steps'][0]['state'],'blocked')
        self.assertTrue(any(e['type']=='turn.completed' and e['turn_id']=='question-while-blocked' for e in self.ws.messages))
        mutator=ScriptedProvider([tool_step('write_file',{'path':'calculator.py','content':'UNAUTHORIZED'})])
        await self.server.run_tool_turn(self.ws,thread_id=self.thread.id,turn_id='blocked-write',prompt='Change it',model='mock',provider=mutator,unified=True,deferred_plan_ids=[pid])
        self.assertIn('a-b',(self.repo/'calculator.py').read_text())
        self.assertTrue(any(e['type']=='turn.failed' and e['payload'].get('code')=='PLAN_RESUME_CONFIRMATION_REQUIRED' for e in self.ws.messages))

    async def test_text_only_model_answers_without_tool_schemas(self):
        class TextOnly(ScriptedProvider):
            agent_tools_enabled=False
            async def stream_chat(self,**kwargs):
                self_outer.assertIsNone(kwargs.get('tools'))
                async for chunk in super().stream_chat(**kwargs):yield chunk
        self_outer=self
        p=TextOnly([final_step('回答')])
        await self.server.run_tool_turn(self.ws,thread_id=self.thread.id,turn_id='text-only',prompt='问题',model='text-only',provider=p,unified=True)
        self.assertEqual(p.calls,1)
        self.assertEqual(self.server.store.task_plans.list_for_thread(self.thread.id),[])

    async def test_diagnostic_export_is_short_private_and_preserves_evidence(self):
        _,r=await self.run_steps([tool_step('write_file',{'path':'calculator.py','content':'def add(a,b): return a+b\n'}),final_step('完成')])
        before=self.server.store.task_plans.executions(r['plan_id'])
        ws=FakeWebSocket()
        await self.server.tasks.handle(ws,{'type':'task.runtime.diagnostics','thread_id':self.thread.id,'payload':{'run_id':r['id']}},set())
        output=ws.messages[-1]['payload']
        self.assertLessEqual(len(output['markdown'].splitlines()),150)
        self.assertTrue(Path(output['json_path']).is_file())
        value=json.loads(Path(output['json_path']).read_text(encoding='utf-8'))
        self.assertEqual(len(value['executions']),len(before))
        self.assertNotIn('goal',value['plan'])
        self.assertNotIn('stdout',value['runtime']['verification'][0])
        self.assertEqual(self.server.store.task_plans.executions(r['plan_id']),before)

    async def test_real_protocol_preflight_rejects_zero_before_turn_started(self):
        self.server.ensure_model_available=AsyncMock(return_value=True)
        self.server.provider=ScriptedProvider([final_step('not sent')])
        self.server.store.set_setting('orchestration.config',json.dumps(validate_config({'budget':{'api_calls':0}})))
        await self.server.handle_message(self.ws,{'type':'turn.start','thread_id':self.thread.id,'payload':{'prompt':'question','model':'mock','unified':True}},set())
        self.assertEqual(self.server.provider.calls,0)
        self.assertFalse(any(e['type']=='turn.started' for e in self.ws.messages))
        self.assertIn('api_calls',self.ws.messages[-1]['payload']['message'])
        self.assertEqual(self.project.state.get_messages(self.thread.id),[])

    async def test_intermediate_step_does_not_run_future_module_tests_but_final_does(self):
        (self.repo/'tests/test_future.py').write_text('import unittest\nimport newmodule\nclass Future(unittest.TestCase):\n def test_future(self): self.assertTrue(newmodule.ready())\n')
        _,r=await self.run_steps([tool_step('agent_plan',{'steps':[{'description':'Repair current calculator'},{'description':'Implement the future module and verify the whole project'}]}),tool_step('write_file',{'path':'calculator.py','content':'def add(a,b): return a+b\n'}),final_step('当前步骤代码已修改'),tool_step('write_file',{'path':'newmodule.py','content':'def ready(): return True\n'}),final_step('完成全部实现')])
        self.assertEqual(r['outcome'],'completed_verified')
        self.assertTrue(all(s['state']=='completed' for s in r['plan']['steps']))
        row=self.server.store.connection.execute('SELECT data_json FROM agent_execution_runs WHERE id=?',(r['id'],)).fetchone()
        history=json.loads(row[0])['unified_verification_history']
        self.assertEqual(history[0]['level'],'basic')
        self.assertIn('unittest',history[-1]['results'][0]['command'])
        self.assertTrue(history[-1]['results'][0]['ok'])

    async def test_real_protocol_persists_one_user_message_not_two(self):
        self.server.ensure_model_available=AsyncMock(return_value=True)
        self.server.provider=ScriptedProvider([final_step('Answer')])
        await self.server.handle_message(self.ws,{'type':'turn.start','thread_id':self.thread.id,'payload':{'prompt':'Question','model':'mock','unified':True}},set())
        await asyncio.gather(*self.server.active_turns.values())
        messages=self.project.state.get_messages(self.thread.id)
        self.assertEqual([m['role'] for m in messages],['user','assistant'])
        self.assertEqual(messages[0]['content'],'Question')

    async def test_websocket_disconnect_keeps_server_owned_mcp_and_records_pause(self):
        from aiohttp import web
        from aiohttp.test_utils import TestClient,TestServer
        self.server.mcp_runtime.close=AsyncMock()
        app=web.Application();app.router.add_get('/ws',self.server.websocket)
        async with TestClient(TestServer(app)) as client:
            ws=await client.ws_connect('/ws',headers={'Authorization':'Bearer test'})
            await ws.receive_json();await ws.close();await asyncio.sleep(.05)
        self.server.mcp_runtime.close.assert_not_awaited()

    async def test_frozen_profile_uses_original_endpoint_model_timeout_and_prices(self):
        provider=ScriptedProvider([])
        self.server.tasks.provider_factory_override=lambda route,profile:provider
        snapshot={'profile':{'model_profile_id':'original','route':'api','model':'original-model','output_limit':1024,'input_price':1,'output_price':2,
                             '_connection':{'connection_id':'old','credential_reference':'fixture'}},'capabilities':{'text':'PASS','tools':'PASS'},'request_seconds':17}
        with patch.object(self.server.tasks,'catalog',side_effect=AssertionError('Snapshot restoration must not read a changed catalog')):
            restored,model=self.server.chat_provider('profile:original',snapshot)
        self.assertEqual(model,'original-model');self.assertEqual(restored.request_timeout,17)
        self.assertEqual(restored.billing_prices,{'input_price':1,'output_price':2})

    async def test_active_websocket_loss_persists_pause_usage_and_clears_running_ids(self):
        from aiohttp import web
        from aiohttp.test_utils import TestClient,TestServer
        from test_agent_reliability import BlockingProvider
        provider=BlockingProvider();self.server.provider=provider
        self.server.ensure_model_available=AsyncMock(return_value=True)
        app=web.Application();app.router.add_get('/ws',self.server.websocket)
        async with TestClient(TestServer(app)) as client:
            ws=await client.ws_connect('/ws',headers={'Authorization':'Bearer test'});await ws.receive_json()
            await ws.send_json({'type':'turn.start','thread_id':self.thread.id,'payload':{'model':'mock','prompt':'真实连接中断测试','unified':True}})
            await asyncio.wait_for(provider.started.wait(),10)
            await ws.close()
            for _ in range(100):
                if not self.server.active_turns:break
                await asyncio.sleep(.02)
        ws=FakeWebSocket();await self.server.tasks.handle(ws,{'type':'task.runtime.list','thread_id':self.thread.id,'payload':{}},set())
        payload=ws.messages[-1]['payload']
        self.assertEqual(payload['active_turn_ids'],[])
        self.assertEqual(payload['runtimes'][0]['phase'],'paused')
        self.assertEqual(payload['runtimes'][0]['outcome'],'awaiting_user')
        self.assertEqual(self.server.tasks.runtime.usage()['api_calls'],1)
        self.assertEqual(self.project.state.get_messages(self.thread.id)[0]['role'],'user')

    async def test_background_websocket_loss_keeps_execution_and_reconnect_can_cancel(self):
        from aiohttp import web
        from aiohttp.test_utils import TestClient,TestServer
        from test_agent_reliability import BlockingProvider
        provider=BlockingProvider();self.server.provider=provider
        self.server.ensure_model_available=AsyncMock(return_value=True)
        app=web.Application();app.router.add_get('/ws',self.server.websocket)
        async with TestClient(TestServer(app)) as client:
            ws=await client.ws_connect('/ws',headers={'Authorization':'Bearer test'});await ws.receive_json()
            await ws.send_json({'type':'turn.start','thread_id':self.thread.id,'payload':{'model':'mock','prompt':'后台任务断线测试','unified':True,'background':True}})
            await asyncio.wait_for(provider.started.wait(),10)
            ident=next(iter(self.server.active_turns))
            await ws.close();await asyncio.sleep(.05)
            self.assertFalse(self.server.active_turns[ident].done())
            self.assertEqual(self.server.background.list()[0]['state'],'running')
            ws2=await client.ws_connect('/ws',headers={'Authorization':'Bearer test'});await ws2.receive_json()
            await ws2.send_json({'type':'turn.cancel','turn_id':ident,'payload':{}})
            for _ in range(100):
                if ident not in self.server.active_turns:break
                await asyncio.sleep(.02)
            self.assertNotIn(ident,self.server.active_turns)
            self.assertEqual(self.server.background.list()[0]['state'],'cancelled')
            self.assertEqual(self.server.tasks.runtime.usage()['api_calls'],1)
