import json
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from agent.persistence.store import SQLiteStore,SCHEMA_VERSION,default_data_dir
from agent.persistence.backup import create_backup,inspect_backup,restore_backup,DataLock,file_digest
from agent.server.projects import ProjectRegistry


class BackupTests(unittest.TestCase):
    def test_environment_data_directory_cannot_resolve_under_executable_cwd(self):
        with patch.dict('os.environ', {'LCA_DATA_DIR': 'build/pilot'}):
            with self.assertRaisesRegex(ValueError, '绝对路径'):
                default_data_dir()

    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.addCleanup(lambda:self.store.close() if self.store else None);self.root=Path(self.temp.name);self.data=self.root/'data';self.repo=self.root/'project';self.repo.mkdir()
        self.store=SQLiteStore(self.data)
        self.project,self.thread,_=ProjectRegistry(self.store).open(str(self.repo),active_model="mock")
        self.project.state.append_message(self.thread.id,role='user',content='persisted conversation')
        self.plan=self.store.task_plans.create(self.thread.id,'preserve task',[{'description':'inspect','verification':'real command'}])
        self.project.knowledge().save('项目约定','使用 uv 和 unittest',trust='user')
        self.store.set_setting('permission_mode','workspace')
        self.store.set_setting('models.catalog.v1',json.dumps({'connections':[],'profiles':[]}))
        (self.data/'provider-secrets.json').write_text('encrypted-placeholder',encoding='utf-8')

    def tearDown(self):
        if self.store:self.store.close()
        self.temp.cleanup()

    def test_version6_migration_creates_consistent_backup_without_losing_records(self):
        self.store.connection.execute('PRAGMA user_version=6');self.store.connection.commit();self.store.close();self.store=None
        self.store=SQLiteStore(self.data)
        self.assertEqual(self.store.connection.execute('PRAGMA user_version').fetchone()[0],SCHEMA_VERSION)
        backups=list((self.data/'backups').iterdir());self.assertEqual(len(backups),1)
        manifest=inspect_backup(backups[0]);self.assertEqual(manifest['schema'],6)
        self.assertEqual(self.store.connection.execute('SELECT COUNT(*) FROM messages').fetchone()[0],1)
        self.assertEqual(self.store.task_plans.get(self.plan)['goal'],'preserve task')
        self.assertEqual(self.store.get_setting('permission_mode'),'workspace')
        self.assertEqual((backups[0]/'provider-secrets.json').read_text(),'encrypted-placeholder')
        self.assertEqual(self.store.connection.execute('SELECT COUNT(*) FROM project_memories').fetchone()[0],1)

    def test_explicit_restore_preserves_current_data_and_restores_complete_database(self):
        backup=create_backup(self.store.connection,self.data)
        self.store.set_setting('sentinel','after-backup')
        self.store.close();self.store=None
        result=restore_backup(backup['path'],self.data)
        self.assertTrue(result['restored']);self.assertTrue(Path(result['preserved']['path']).is_dir())
        self.store=SQLiteStore(self.data)
        self.assertIsNone(self.store.get_setting('sentinel'))
        self.assertEqual(self.store.task_plans.get(self.plan)['goal'],'preserve task')
        self.assertEqual(self.store.connection.execute('SELECT COUNT(*) FROM messages').fetchone()[0],1)

    def test_backup_tamper_is_detected_and_source_is_not_overwritten(self):
        backup=create_backup(self.store.connection,self.data)
        (Path(backup['path'])/'provider-secrets.json').write_text('tampered')
        self.store.set_setting('must-survive','yes')
        with self.assertRaisesRegex(ValueError,'校验失败'):restore_backup(backup['path'],self.data)
        self.assertEqual(self.store.get_setting('must-survive'),'yes')

    def test_restore_uses_separate_electron_vault_and_preserves_current_encrypted_files(self):
        vault=self.root/'desktop';vault.mkdir();(vault/'model-secrets.json').write_text('encrypted-before')
        backup=create_backup(self.store.connection,self.data,credential_dir=vault)
        (vault/'model-secrets.json').write_text('encrypted-current')
        self.store.close();self.store=None
        with patch.dict('os.environ',{'LCA_DESKTOP_DATA_DIR':str(vault)}):
            result=restore_backup(backup['path'],self.data)
        self.assertEqual((vault/'model-secrets.json').read_text(),'encrypted-before')
        self.assertEqual((Path(result['preserved']['path'])/'model-secrets.json').read_text(),'encrypted-current')

    def test_outside_backup_and_unknown_manifest_paths_are_rejected(self):
        backup=create_backup(self.store.connection,self.data);root=Path(backup['path'])
        manifest=json.loads((root/'manifest.json').read_text(encoding='utf-8'));manifest['files']['../outside']='a'*64
        (root/'manifest.json').write_text(json.dumps(manifest))
        with self.assertRaises(ValueError):inspect_backup(root)
        with self.assertRaises(ValueError):restore_backup(self.repo,self.data)

    def test_low_disk_migration_keeps_original_schema_and_data(self):
        self.store.connection.execute('PRAGMA user_version=6');self.store.connection.commit();self.store.close();self.store=None
        with patch('agent.persistence.backup.shutil.disk_usage',return_value=SimpleNamespace(free=0)):
            with self.assertRaisesRegex(ValueError,'备份空间不足'):SQLiteStore(self.data)
        with closing(sqlite3.connect(self.data/'local-coding-agent.sqlite3')) as db:
            self.assertEqual(db.execute('PRAGMA user_version').fetchone()[0],6)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM messages').fetchone()[0],1)

    def test_future_schema_and_corruption_never_silently_recreate_database(self):
        self.store.connection.execute('PRAGMA user_version=999');self.store.connection.commit();self.store.close();self.store=None
        file=self.data/'local-coding-agent.sqlite3';before=file_digest(file)
        with self.assertRaisesRegex(ValueError,'较新版本'):SQLiteStore(self.data)
        self.assertEqual(before,file_digest(file))
        file.write_bytes(b'corrupt database')
        with self.assertRaises(sqlite3.DatabaseError):SQLiteStore(self.data)
        self.assertEqual(file.read_bytes(),b'corrupt database')

    def test_application_and_offline_restore_locks_are_exclusive_and_released(self):
        with DataLock(self.data):
            with self.assertRaisesRegex(ValueError,'正在使用'):
                with DataLock(self.data):pass
        with DataLock(self.data):pass


if __name__=='__main__':unittest.main()
