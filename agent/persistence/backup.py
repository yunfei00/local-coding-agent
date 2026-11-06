"""Consistent SQLite backup and explicit offline restore, never blind rollback."""
from __future__ import annotations
import hashlib
import json
import os
import shutil
import sqlite3
import time
import uuid
from contextlib import closing
from pathlib import Path

PROTECTED_FILES=('model-secrets.json','provider-secrets.json','mcp-secrets.json','Local State')


def file_digest(path):
    digest=hashlib.sha256()
    with Path(path).open('rb') as source:
        for chunk in iter(lambda:source.read(1024*1024),b''):digest.update(chunk)
    return digest.hexdigest()


def create_backup(connection, data_dir, *, reason='manual', credential_dir=None):
    data=Path(data_dir);root=data/'backups';root.mkdir(exist_ok=True,mode=0o700)
    if root.resolve().parent!=data.resolve():raise ValueError('备份目录不能重定向到应用目录之外')
    pages=connection.execute('PRAGMA page_count').fetchone()[0]*connection.execute('PRAGMA page_size').fetchone()[0]
    needed=max(128*1024*1024,pages*2)
    if shutil.disk_usage(root).free<needed:raise ValueError('备份空间不足；未迁移或删除原数据')
    ident=str(int(time.time()))+'-'+uuid.uuid4().hex[:12]
    temp=root/(ident+'.pending');temp.mkdir(mode=0o700)
    db=temp/'local-coding-agent.sqlite3'
    try:
        with closing(sqlite3.connect(db)) as target:
            connection.backup(target)
            if target.execute('PRAGMA quick_check').fetchone()[0]!='ok':raise ValueError('备份数据库完整性检查失败')
        credentials=Path(credential_dir or data)
        files=[db]
        for name in PROTECTED_FILES:
            source=credentials/name
            if source.is_file() and not source.is_symlink():
                shutil.copy2(source,temp/name);files.append(temp/name)
        manifest={'version':1,'created_at':time.time(),'reason':reason,
                  'schema':connection.execute('PRAGMA user_version').fetchone()[0],
                  'files':{p.name:file_digest(p) for p in files},
                  'credential_note':'加密凭据仍受原 Windows 用户 DPAPI 保护，不保证跨用户恢复'}
        (temp/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
        final=root/ident;temp.replace(final)
        return {'backup_id':ident,'path':str(final),'schema':manifest['schema']}
    except Exception:
        # Keep incomplete backup for diagnosis; never touch source data.
        raise


def inspect_backup(directory):
    root=Path(directory).resolve(strict=True)
    manifest=json.loads((root/'manifest.json').read_text(encoding='utf-8'))
    if manifest.get('version')!=1 or not isinstance(manifest.get('files'),dict):raise ValueError('备份清单无效')
    allowed={'local-coding-agent.sqlite3',*PROTECTED_FILES}
    if not manifest['files'] or set(manifest['files'])-allowed:raise ValueError('备份包含未知路径')
    for name,digest in manifest['files'].items():
        p=root/name
        if p.is_symlink() or file_digest(p)!=digest:raise ValueError('备份校验失败：'+name)
    with closing(sqlite3.connect((root/'local-coding-agent.sqlite3').as_uri()+'?mode=ro',uri=True)) as db:
        if db.execute('PRAGMA quick_check').fetchone()[0]!='ok':raise ValueError('备份数据库损坏')
        if db.execute('PRAGMA user_version').fetchone()[0]!=manifest.get('schema'):raise ValueError('备份数据库版本与清单不一致')
    return manifest


def restore_backup(directory,data_dir):
    """Caller must hold offline application lock; save current data first."""
    root=Path(directory).resolve(strict=True);data=Path(data_dir).resolve(strict=True)
    if root.parent != data/'backups':raise ValueError('仅恢复本应用数据目录内的已校验备份')
    manifest=inspect_backup(root)
    credentials=Path(os.environ.get('LCA_DESKTOP_DATA_DIR') or data).resolve()
    credentials.mkdir(parents=True,exist_ok=True)
    from agent.persistence.store import SCHEMA_VERSION
    if manifest['schema']>SCHEMA_VERSION:raise ValueError('备份来自较新版本，未覆盖当前数据')
    current=data/'local-coding-agent.sqlite3'
    with closing(sqlite3.connect(current)) as connection:
        connection.execute('BEGIN EXCLUSIVE');connection.rollback()
        preserved=create_backup(connection,data,reason='before-explicit-restore',credential_dir=credentials)
        with closing(sqlite3.connect((root/'local-coding-agent.sqlite3').as_uri()+'?mode=ro',uri=True)) as source:source.backup(connection)
        connection.commit()
    for name in PROTECTED_FILES:
        if name in manifest['files']:
            temp=credentials/(name+'.restore.tmp');shutil.copy2(root/name,temp);temp.replace(credentials/name)
    return {'restored':True,'preserved':preserved,'restart_required':True}


class DataLock:
    """Process lifetime lock used by server launcher and offline recovery CLI."""
    def __init__(self,data_dir):
        self.path=Path(data_dir)/'application-data.lock';self.file=None

    def __enter__(self):
        self.path.parent.mkdir(parents=True,exist_ok=True)
        handle=self.path.open('a+b')
        if self.path.stat().st_size==0:handle.write(b'0');handle.flush()
        handle.seek(0)
        try:
            if os.name=='nt':
                import msvcrt
                msvcrt.locking(handle.fileno(),msvcrt.LK_NBLCK,1)
            else:
                import fcntl
                fcntl.flock(handle,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except OSError:
            handle.close();raise ValueError('应用数据正在使用；请完整退出应用后再恢复或启动')
        self.file=handle;return self

    def __exit__(self,*_):
        if self.file:
            self.file.seek(0)
            if os.name=='nt':
                import msvcrt
                msvcrt.locking(self.file.fileno(),msvcrt.LK_UNLCK,1)
            else:
                import fcntl
                fcntl.flock(self.file,fcntl.LOCK_UN)
            self.file.close();self.file=None
