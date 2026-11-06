"""仅为本仓库隔离安装验收生成 v0.9 合成历史并核验迁移；不制造任务成功证据。"""
import argparse
import hashlib
import json
import sqlite3
import sys
from pathlib import Path
from contextlib import closing

ROOT=Path(__file__).resolve().parents[2]


def digest(file):
    return hashlib.sha256(file.read_bytes()).hexdigest()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation',choices=['seed','verify'])
    parser.add_argument('--source',type=Path,required=True)
    parser.add_argument('--data',type=Path,required=True)
    args=parser.parse_args()
    source=args.source.resolve();data=args.data.resolve()
    if not source.is_relative_to(ROOT) or not data.is_relative_to(ROOT/'build'):
        parser.error('只允许本仓库源码与 build 隔离数据；禁止真实用户历史目录')
    sys.path.insert(0,str(source))
    from agent.persistence.store import SQLiteStore,SCHEMA_VERSION
    from agent.server.projects import ProjectRegistry
    snapshot=data/'upgrade-contract.json'
    if args.operation=='seed':
        if SCHEMA_VERSION!=6:parser.error('必须使用真实 v0.9 schema 6 源码建立旧数据')
        store=SQLiteStore(data)
        try:
            folder=data/'保留用户工程';folder.mkdir()
            (folder/'original.txt').write_text('升级不得覆盖的合成用户文件',encoding='utf-8')
            project,thread,_=ProjectRegistry(store).open(str(folder),active_model=None)
            project.state.append_message(thread.id,role='user',content='合成旧会话：升级保留，不代表任何任务已执行')
            plan=store.task_plans.create(thread.id,'待恢复的合成任务',[{'description':'未执行步骤','verification':'必须真实运行后才可完成'}])
            checkpoint=store.task_plans.checkpoint(plan,'安装升级前：步骤尚未执行')
            project.knowledge().save('升级约定','保留原工程、历史、凭据和待执行步骤',trust='user')
            store.set_setting('v10.upgrade.canary','retained')
            store.set_setting('permission_mode','workspace')
            snapshot.write_text(json.dumps({'project':project.id,'thread':thread.id,'plan':plan,'checkpoint':checkpoint,
                'original':str(folder/'original.txt'),'digest':digest(folder/'original.txt'),
                'encrypted_files':{p.name:digest(p) for p in (data/'desktop').glob('*-secrets.json')}}),encoding='utf-8')
        finally:store.close()
        print(json.dumps({'seeded':True,'schema':6,'task_state':'pending'},ensure_ascii=False))
        return
    # Verify that the installed application already migrated it, before opening a source store.
    with closing(sqlite3.connect((data/'local-coding-agent.sqlite3').as_uri()+'?mode=ro',uri=True)) as db:
        assert db.execute('PRAGMA user_version').fetchone()[0]==7,'安装版尚未迁移，禁止由验收脚本代替迁移'
    contract=json.loads(snapshot.read_text(encoding='utf-8'));store=SQLiteStore(data)
    try:
        assert store.get_setting('v10.upgrade.canary')=='retained'
        assert store.get_setting('permission_mode')=='workspace'
        assert all(step['state']=='pending' for step in store.task_plans.get(contract['plan'])['steps'])
        assert store.task_plans.latest_checkpoint(contract['plan'])['id']==contract['checkpoint']
        assert store.connection.execute('SELECT COUNT(*) FROM messages WHERE thread_id=?',(contract['thread'],)).fetchone()[0]>=1
        assert store.connection.execute('SELECT COUNT(*) FROM project_memories WHERE project_id=?',(contract['project'],)).fetchone()[0]==1
        assert digest(Path(contract['original']))==contract['digest']
        assert all(digest(data/'desktop'/name)==value for name,value in contract['encrypted_files'].items())
        assert any((data/'backups').iterdir())
    finally:store.close()
    print(json.dumps({'result':'PASS','schema':7,'history':True,'pending_task':True,'checkpoint':True,'memory':True,
        'original_file':True,'encrypted_files':True,'migration_backup':True},ensure_ascii=False))


if __name__=='__main__':main()
