"""Recoverable one-file deletion; no recursive directories or credential targets."""
import json
import os
import shutil
import uuid
from pathlib import Path
from agent.tools.base import BaseTool,ToolError,ToolResult


class DeleteFileTool(BaseTool):
    name='delete_file'
    description='删除一个明确指定的普通文件（先移动到应用恢复目录）。不递归删除目录，不删除凭据或系统文件。'
    parameters={'type':'object','required':['path'],'properties':{'path':{'type':'string'}}}

    def __init__(self,workspace):self.workspace=workspace

    async def execute(self,arguments,*,on_output=None):
        raw=Path(arguments['path']);candidate=raw if raw.is_absolute() else self.workspace.root/raw
        if candidate.is_symlink():raise ToolError('DELETE_TARGET_UNSAFE','不删除符号链接')
        target=self.workspace.resolve(str(raw),must_exist=True)
        if not target.is_file() or target.stat().st_size>32*1024*1024:
            raise ToolError('DELETE_TARGET_UNSAFE','仅允许删除单个不超过32MiB的普通文件')
        if target.name.lower() in {'.env','id_rsa','id_ed25519','credentials','model-secrets.json','provider-secrets.json'} or any(p.lower() in {'.git','.ssh'} for p in target.parts):
            raise ToolError('DELETE_TARGET_UNSAFE','凭据或 Git 内部文件不能通过此工具删除')
        system=os.getenv('WINDIR')
        if system and Path(system).resolve() in target.parents:
            raise ToolError('DELETE_TARGET_UNSAFE','系统文件受保护')
        root=Path(os.getenv('LCA_DATA_DIR') or Path.home()/'.local-coding-agent')/'file-recovery'
        root.mkdir(parents=True,exist_ok=True)
        if shutil.disk_usage(root).free<target.stat().st_size+16*1024*1024:
            raise ToolError('DELETE_BACKUP_SPACE','恢复目录磁盘空间不足，未删除')
        ident=uuid.uuid4().hex
        manifest=root/(ident+'.json');manifest.write_text(json.dumps({'original_path':str(target),'backup':ident+'.bin'},ensure_ascii=False),encoding='utf-8')
        shutil.move(str(target),str(root/(ident+'.bin')))
        relative=self.workspace.relative(target)
        return ToolResult(ok=True,summary='文件已移入本机恢复目录',data={'path':relative,'recovery_id':ident},changed_paths=[relative])
