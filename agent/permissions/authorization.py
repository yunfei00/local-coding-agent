"""User-owned scoped authorization, separate from model prompts and credentials."""
from __future__ import annotations

import json
import time
from agent.permissions.policy import PermissionMode, PermissionPolicy, parse_permission_mode


class AuthorizationSettings:
    KEY = 'permission.v1'

    def __init__(self, store):
        self.store = store
        store.connection.execute('CREATE TABLE IF NOT EXISTS permission_audit (id INTEGER PRIMARY KEY, at REAL NOT NULL, project_id TEXT, task_id TEXT, tool TEXT, mode TEXT, decision TEXT, risk TEXT)')
        store.connection.commit()

    def load(self):
        raw = self.store.get_setting(self.KEY)
        if raw:
            data = json.loads(raw)
            if data.get('version') != 1:
                raise ValueError('权限配置版本不兼容，未清空授权；请恢复备份或更新软件')
            if not isinstance(data.get('full_access_confirmed'),bool) or not isinstance(data.get('revision'),int) or data['revision']<0:
                raise ValueError('权限配置损坏，未清空；请检查备份')
            parse_permission_mode(data.get('global'))
            for scope in ('projects','tasks'):
                values=data.get(scope)
                if not isinstance(values,dict) or any(not isinstance(k,str) or not k for k in values):raise ValueError('权限范围配置损坏')
                for mode in values.values():parse_permission_mode(mode)
            return data
        old = self.store.get_setting('permission_mode') or 'workspace'
        # v0.9 Full Access had different semantics; never silently expand it.
        return {'version':1,'global':old if old != 'full_access' else 'workspace',
                'projects':{},'tasks':{},'full_access_confirmed':False,'revision':0}

    def configure(self, mode, *, scope='global', target=None, confirmed=False):
        if scope not in {'global','project','task'} or scope != 'global' and not target:
            raise ValueError('选择有效的授权范围和目标')
        if mode != 'inherit':
            mode = parse_permission_mode(mode).value
        elif scope == 'global':
            raise ValueError('全局权限不能继承')
        data = self.load()
        if mode == 'full_access' and not data['full_access_confirmed']:
            if confirmed is not True:
                raise ValueError('FULL_ACCESS_CONFIRMATION_REQUIRED：首次完全访问须明确确认风险')
            data['full_access_confirmed'] = True
        if scope == 'global':
            data['global'] = mode
        elif mode == 'inherit':
            data[scope+'s'].pop(target,None)
        else:
            data[scope+'s'][target] = mode
        data['revision'] += 1
        self.store.set_setting(self.KEY,json.dumps(data))
        self.audit(target if scope=='project' else None,target if scope=='task' else None,'permission.set',mode,'configured',scope)
        return data

    def effective(self, project_id=None, task_id=None):
        data = self.load()
        mode = data['tasks'].get(task_id,data['projects'].get(project_id,data['global']))
        return PermissionPolicy(parse_permission_mode(mode),continuous=mode=='full_access' and data['full_access_confirmed'])

    def audit(self, project_id, task_id, tool, mode, decision, risk):
        # No arguments, user file bodies or credentials in authorization logs.
        with self.store.connection:
            self.store.connection.execute('INSERT INTO permission_audit(at,project_id,task_id,tool,mode,decision,risk) VALUES(?,?,?,?,?,?,?)',
                (time.time(),project_id,task_id,tool,mode,decision,risk))


def continuous_verdict(policy, tool, arguments, workspace, metadata, prompt):
    """Extra mode, not a sandbox. Obvious destructive/security actions stay gated."""
    from agent.permissions.policy import PermissionVerdict, WORKSPACE_TOOLS, _NEGATED_COMMIT, _NEGATED_PUSH, _NEGATED_WORKTREE, project_command_risk
    import re
    text = str(arguments.get('command',''))
    nested=project_command_risk(workspace,text,str(arguments.get('cwd') or '.')) if tool in {'run_command','start_process'} else None
    if nested and nested[0]=='system_protection':
        return PermissionVerdict(False,reason=nested[1],risk=nested[0])
    if nested and (nested[0]=='git_commit' and _NEGATED_COMMIT.search(prompt or '') or nested[0]=='git_publish' and _NEGATED_PUSH.search(prompt or '')):
        return PermissionVerdict(False,reason='项目脚本违反本任务 Git 限制',risk='user_constraint')
    if re.search(r'(?i)(?:\.ssh[/\\]|\bid_(?:rsa|ed25519)\b|(?<![\w])\.env(?![\w.]|\.example)|model-secrets\.json|provider-secrets\.json|os\.environ|\$env:(?:.*key|.*token|.*password))',text):
        return PermissionVerdict(False,reason='命令可能读取或外传凭据，未执行',risk='credential_access')
    if re.search(r'(?i)(?:-verb\s+runas|disable.*(?:antivirus|realtime)|set-mppreference|bcdedit|diskpart|\bformat\s+[a-z]:|takeown\b)',text):
        return PermissionVerdict(False,reason='完全访问不授权提权或禁用系统安全机制',risk='system_protection')
    if tool not in WORKSPACE_TOOLS and metadata.get('source') != 'mcp':
        return PermissionVerdict(False,reason='未知工具不能由完全访问放行',risk='unknown_tool')
    path = str(arguments.get('path','')).replace('\\','/').casefold()
    if path and (path.rsplit('/',1)[-1] in {'.env','id_rsa','id_ed25519','credentials','model-secrets.json','provider-secrets.json','cookies'} or '/.ssh/' in path):
        return PermissionVerdict(False,reason='凭据文件受保护，请使用安全配置入口',risk='credential_access')
    if any(re.search(r'(?i)(?:api[_-]?key|password|authorization|cookie|private[_-]?key)',str(k)) and v for k,v in arguments.items()):
        return PermissionVerdict(False,reason='不通过工具参数传输凭据',risk='credential_transport')
    if (tool=='git_commit' or metadata.get('risk')=='git_commit' or re.search(r'(?i)\bgit\b[^;&|\n]*\bcommit\b',text)) and _NEGATED_COMMIT.search(prompt or ''):
        return PermissionVerdict(False,reason='本任务明确禁止提交',risk='user_constraint')
    if (metadata.get('risk')=='git_publish' or re.search(r'(?i)\bgit\b[^;&|\n]*\bpush\b',text)) and _NEGATED_PUSH.search(prompt or ''):
        return PermissionVerdict(False,reason='本任务明确禁止推送',risk='user_constraint')
    if tool in {'git_worktree_create','git_worktree_remove'} and _NEGATED_WORKTREE.search(prompt or ''):
        return PermissionVerdict(False,reason='本任务明确禁止改变工作树',risk='user_constraint')
    high = re.search(r'(?i)(\bgit\b[^\n]*(?:--force|-f\b|--delete|reset\s+--hard|clean\s+-)|\brm\s+-|remove-item\b[^\n]*-(?:recurse|force)|\b(?:rd|rmdir)\b|\b(?:curl|invoke-webrequest)\b[^\n]*(?:token|secret|password)|\b(?:gh\s+pr\s+merge|gh\s+release|npm\s+publish)\b)',text)
    bulk=arguments.get('recursive') is True or arguments.get('force') is True or any(isinstance(v,list) and len(v)>100 for v in arguments.values())
    if high or bulk or nested and nested[0] in {'delete','publish','system_admin','git_destructive','project_script'} or metadata.get('risk') in {'delete','destructive','mcp_destructive','system_admin','publish','git_destructive','credential_transport'}:
        return PermissionVerdict(True,True,'高风险、远程合并或发布需要本任务单独授权','high:'+json.dumps(arguments,sort_keys=True), 'high_risk')
    if tool.startswith('desktop_') and arguments.get('scope')=='screen':
        return PermissionVerdict(True,True,'整屏超出单窗口授权，需要单独确认','desktop-screen:'+str(arguments.get('window_id')), 'desktop_share')
    return PermissionVerdict(True,reason='有效完全访问授权；遵守系统权限、目标绑定和任务限制',risk='full_access')
