import json
import os
from pathlib import Path
import tempfile
import unittest
from agent.persistence.store import SQLiteStore
from agent.server.projects import ProjectRegistry
from agent.core.project_files import ProjectFiles
from agent.core.repository_map import RepositoryMap

class KnowledgeTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.base=Path(self.temp.name)
        self.root=self.base/'project';self.root.mkdir();self.store=SQLiteStore(self.base/'data')
        self.project,_,_=ProjectRegistry(self.store).open(self.root,active_model=None)
        self.k=self.project.knowledge()
    def tearDown(self):self.store.close();self.temp.cleanup()
    def write(self,name,text):
        p=self.root/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_text(text,encoding='utf-8');return p
    def test_memory_persists_new_thread_restart_and_project_isolation(self):
        self.k.save('约定','使用 uv 和 unittest','convention',trust='user')
        second=self.base/'other';second.mkdir();p,_,_=ProjectRegistry(self.store).open(second,active_model=None)
        self.assertEqual(p.knowledge().list(),[])
        self.store.close();self.store=SQLiteStore(self.base/'data');project=ProjectRegistry(self.store).get(self.project.id)
        thread=project.state.create_thread(title='新会话',active_model=None)
        self.assertIsNotNone(thread.id);self.assertIn('unittest',project.knowledge().context('测试')[0])
    def test_dedup_edit_optimistic_revision_and_delete(self):
        item=self.k.save('设计','旧决策');same=self.k.save('设计','旧决策');self.assertEqual(item['id'],same['id']);self.assertEqual(same['revision'],1)
        current=self.k.save('设计','新决策',trust='user',expected_revision=1);self.assertEqual(current['revision'],2)
        with self.assertRaisesRegex(ValueError,'刷新'):self.k.save('设计','过期编辑',expected_revision=1)
        self.k.delete(item['id']);self.assertEqual(self.k.list(),[])
    def test_source_change_marks_stale_then_verified_refresh(self):
        self.write('README.md','first')
        self.k.save('来源','初始事实',trust='verified',sources=['README.md'])
        self.write('README.md','second');self.assertTrue(self.k.list()[0]['stale'])
        self.assertNotIn('初始事实',self.k.context('来源')[0])
        self.k.save('来源','当前事实',trust='verified',sources=['README.md']);self.assertFalse(self.k.list('来源')[0]['stale'])
    def test_auto_off_blocks_only_automatic_facts_not_explicit_user_memory(self):
        self.k.set_auto(False);self.k.context('hello');self.assertEqual(self.k.list(),[])
        self.k.save('用户要求','记住这条');self.assertEqual(len(self.k.list()),1)
    def test_credentials_rejected_without_partial_write(self):
        for content in ['api_key=example-secret-value','password="password123"','Cookie: abcdef=xyz','数据库密码：synthetic-value','访问令牌是example-token','-----BEGIN '+'OPENSSH '+'PRIVATE KEY-----','sk-example-token-987654']:
            with self.assertRaises(ValueError):self.k.save('不允许',content)
        self.assertEqual(self.k.list(),[])
    def test_credential_annotations_remain_searchable_but_real_values_and_known_keys_do_not(self):
        self.write('client.py','import os\napi_key: str\napi_key = os.getenv("DEMO_KEY")\ndef build_client(): pass\n')
        self.assertEqual(self.k.search('build_client','symbol')['results'][0]['path'],'client.py')
        self.k.exact_secrets=('opaque-known-value-12345',)
        self.write('note.txt','opaque-known-value-12345')
        self.assertEqual(self.k.search('opaque-known-value')['results'],[])
        with self.assertRaises(ValueError):self.k.save('不保存','opaque-known-value-12345')
    def test_candidate_cannot_overwrite_verified_or_user_rule(self):
        self.k.save('约定','使用 uv',trust='user')
        with self.assertRaises(ValueError):self.k.save('约定','改成其他包管理器')
        self.assertEqual(self.k.list()[0]['content'],'使用 uv')
    def test_external_source_cannot_be_saved_even_full_access(self):
        outside=self.base/'outside.txt';outside.write_text('private');self.project.workspace.set_full_access(True)
        with self.assertRaises(ValueError):self.k.save('越界','不应保存',sources=[str(outside)])
    def test_filename_content_symbol_and_exact_lines(self):
        self.write('src/calculation.py','"""Calculation."""\n\ndef apply_discount(value):\n    return value - 2\n')
        for mode,query in [('filename','calculation.py'),('content','return value'),('symbol','apply_discount')]:
            result=self.k.search(query,mode)['results'][0];self.assertEqual(result['path'],'src/calculation.py')
            text=(self.root/result['path']).read_text().splitlines();self.assertEqual(result['snippet'],'\n'.join(text[result['start_line']-1:result['end_line']]))
            self.assertGreater(result['index_version'],0)
    def test_incremental_update_and_delete(self):
        self.write('a.ts','export function oldName() {}');first=self.k.index();self.assertEqual(self.k.index()['changed'],0)
        self.write('a.ts','export function newName() {}');second=self.k.index();self.assertEqual(second['changed'],1);self.assertGreater(second['version'],first['version'])
        self.assertEqual(self.k.search('oldName')['results'],[])
        (self.root/'a.ts').unlink();self.assertEqual(self.k.index()['deleted'],1);self.assertEqual(self.k.search('newName')['results'],[])
    def test_gitignore_nested_negation_exclude_and_secret_binary_large(self):
        self.write('.gitignore','ignored/\n*.log\n!allowed.log\n');self.write('.lca/exclude','excluded.txt\n')
        for name,text in [('ignored/bad.py','badfact'),('errors.log','badfact'),('excluded.txt','badfact'),('.env','badfact'),('credentials.json','badfact'),('secret.py','api_key="not-a-real-secret"'),('binary.txt','badfact\0'),('huge.md','x'*300000),('node_modules/a.js','badfact')]:self.write(name,text)
        self.write('allowed.log','goodfact');self.write('src/.gitignore','private.py\n');self.write('src/private.py','badfact')
        self.assertEqual(self.k.search('badfact')['results'],[]);self.assertEqual(self.k.search('goodfact')['results'][0]['path'],'allowed.log')
    def test_repository_map_obeys_same_boundaries(self):
        self.write('.gitignore','hidden.py\n');self.write('hidden.py','def hidden(): pass');self.write('visible.py','def visible(): pass')
        repo=RepositoryMap(self.root);repo.build();self.assertNotIn('hidden.py',repo.files);self.assertIn('visible.py',repo.files)
    def test_dependency_build_metadata_is_not_source_change_or_retrieval_content(self):
        from agent.core.unified_runtime import workspace_snapshot
        self.write('math.py','def add(a,b): return a+b')
        baseline=workspace_snapshot(self.root)
        self.write('vendor/pkg/demo.egg-info/PKG-INFO','generated dependency metadata')
        self.write('demo.dist-info/METADATA.txt','generated dependency metadata')
        self.assertEqual(workspace_snapshot(self.root),baseline)
        self.assertEqual(self.k.search('dependency')['results'],[])
        self.write('math.py','def add(a,b): return a-b')
        self.assertNotEqual(workspace_snapshot(self.root),baseline)
    def test_same_size_same_timestamp_source_write_is_detected(self):
        from agent.core.unified_runtime import workspace_snapshot,changed_since_snapshot
        file=self.write('math.py','def add(a,b): return a+b');stamp=file.stat().st_mtime_ns
        before=workspace_snapshot(self.root)
        self.write('math.py','def add(a,b): return a-b');os.utime(file,ns=(stamp,stamp))
        after=workspace_snapshot(self.root)
        self.assertEqual(before['math.py'][:2],after['math.py'][:2])
        self.assertEqual(changed_since_snapshot(before,after),{'math.py'})
    def test_noop_write_is_not_progress_and_legacy_checkpoint_stays_compatible(self):
        from agent.core.unified_runtime import workspace_snapshot,changed_since_snapshot,snapshot_fingerprint
        file=self.write('math.py','def add(a,b): return a+b');before=workspace_snapshot(self.root)
        legacy={p:value[:2] for p,value in before.items()}
        self.assertEqual(changed_since_snapshot(legacy,before),set())
        self.write('math.py','def add(a,b): return a+b');os.utime(file,ns=(file.stat().st_atime_ns,file.stat().st_mtime_ns+1000000000))
        after=workspace_snapshot(self.root)
        self.assertEqual(changed_since_snapshot(before,after),set())
        self.assertEqual(snapshot_fingerprint(before),snapshot_fingerprint(after))
    def test_corrupted_index_rebuilt_without_touching_memory(self):
        self.write('a.py','def found(): pass');self.k.save('保持','项目记忆');self.k.index()
        with self.store.connection:self.store.connection.execute("UPDATE project_knowledge_files SET symbols='broken' WHERE project_id=?",(self.project.id,))
        self.assertEqual(self.k.search('found','symbol')['results'][0]['start_line'],1);self.assertEqual(self.k.list()[0]['content'],'项目记忆')
        self.store.set_setting('knowledge.index:'+self.project.id,'[]')
        self.assertTrue(self.k.index()['recovered'])
        with self.store.connection:self.store.connection.execute("UPDATE project_knowledge_files SET symbols='broken' WHERE project_id=?",(self.project.id,))
        (self.root/'a.py').unlink()
        self.assertEqual(self.k.index()['deleted'],1)
        self.assertEqual(self.store.connection.execute('SELECT count(*) FROM project_knowledge_files').fetchone()[0],0)
    def test_explicit_rule_authorization_is_per_owner_and_logs_hide_contents(self):
        from agent.tools.knowledge import ProjectMemoryTool
        from agent.tools.base import ToolError
        from agent.desktop.runtime import public_arguments
        tool=ProjectMemoryTool(self.k);self.k.set_auto(False)
        self.k.explicit_save_owners={'authorized'};self.k.explicit_rules={'authorized':['使用 unittest']}
        with self.assertRaises(ToolError):tool._execute({'action':'save','title':'约定','content':'使用 unittest'},owner_id='other')
        saved=tool._execute({'action':'save','title':'约定','content':'使用 unittest'},owner_id='authorized')
        self.assertEqual(saved.data['memory']['trust'],'user')
        for name in ['project_memory','project_memory_search','knowledge_search']:
            self.assertNotIn('sensitive project text',str(public_arguments(name,{'content':'sensitive project text','query':'sensitive project text'})))
    def test_symlink_escape_and_ignored_file_removed_from_existing_index(self):
        self.write('a.py','def hidden_after(): pass');self.k.index();self.write('.gitignore','a.py\n')
        self.assertEqual(self.k.search('hidden_after')['results'],[])
        outside=self.base/'private.py';outside.write_text('externalfact')
        try:(self.root/'link.py').symlink_to(outside)
        except OSError:
            # Windows without symlink privilege: boundary is still verified with a literal external path.
            self.assertFalse(ProjectFiles(self.root).allowed(outside));return
        self.assertEqual(self.k.search('externalfact')['results'],[])
    def test_old_schema_migration_preserves_chat_and_memory_transaction_rollback(self):
        with self.store.connection:self.store.connection.execute('PRAGMA user_version=5')
        self.store.close();self.store=SQLiteStore(self.base/'data');self.assertEqual(self.store.connection.execute('PRAGMA user_version').fetchone()[0],6)
        p=ProjectRegistry(self.store).get(self.project.id);self.assertIsNotNone(p);k=p.knowledge();k.save('保留','旧内容')
        with self.assertRaises(ValueError):k.save('保留','bad password=secret123')
        self.assertEqual(k.list()[0]['content'],'旧内容')
    def test_sql_write_failure_preserves_memory_and_next_write_recovers(self):
        import sqlite3
        self.k.save('原记录','必须保留',trust='user')
        self.store.connection.execute("CREATE TRIGGER reject_memory_update BEFORE UPDATE ON project_memories BEGIN SELECT RAISE(ABORT, 'controlled storage fault'); END")
        with self.assertRaises(sqlite3.IntegrityError):self.k.save('原记录','新的内容',trust='user')
        self.assertEqual(self.k.list()[0]['content'],'必须保留');self.assertEqual(self.k.list()[0]['revision'],1)
        self.store.connection.execute('DROP TRIGGER reject_memory_update')
        updated=self.k.save('原记录','恢复后内容',trust='user')
        self.assertEqual(updated['revision'],2)
