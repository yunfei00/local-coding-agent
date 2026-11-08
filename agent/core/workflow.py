"""DAG metadata and role policy for the existing TaskPlanStore/Agent loop.

No model client, tool executor or alternate execution loop lives here.
"""
from __future__ import annotations

import copy
import re
import json
import hashlib
from enum import StrEnum


class WorkflowState(StrEnum):
    CREATED='CREATED'
    READY='READY'
    RUNNING='RUNNING'
    WAITING_APPROVAL='WAITING_APPROVAL'
    BLOCKED='BLOCKED'
    FAILED='FAILED'
    COMPLETED='COMPLETED'
    CANCELLED='CANCELLED'


def workflow_state(runtime):
    phase=runtime.get('phase')
    if phase=='cancelled':return WorkflowState.CANCELLED
    if phase=='failed':return WorkflowState.FAILED
    if phase in {'paused','blocked'} or runtime.get('outcome') in {'awaiting_user','partially_completed','completed_unverified'}:return WorkflowState.BLOCKED
    if phase=='completed':return WorkflowState.COMPLETED
    if phase=='queued':return WorkflowState.READY
    if phase in {'executing','planning','verifying','repairing'}:return WorkflowState.RUNNING
    return WorkflowState.CREATED

ROLES = ('planner', 'developer', 'reviewer', 'tester')
MAX_NODES = 30
ADJUST_TOOL={'type':'function','function':{'name':'workflow_adjust','description':'Planner/Developer: refine pending DAG steps after actual inspection. Never changes started/completed steps or their roles. At most 3 successful adjustments per run.',
    'parameters':{'type':'object','required':['reason','changes'],'properties':{'reason':{'type':'string','minLength':1,'maxLength':2000},'changes':{'type':'array','minItems':1,'maxItems':30,'items':{'type':'object','required':['task_id'],'properties':{
        'task_id':{'type':'string'},'description':{'type':'string','maxLength':4000},'verification':{'type':'string','maxLength':2000},'title':{'type':'string','maxLength':200},
        'dependencies':{'type':'array','items':{'type':'string'}},'acceptance_criteria':{'type':'array','items':{'type':'string'}},'required_capabilities':{'type':'array','items':{'type':'string'}}}}}}}}}
REVIEW_TOOL = {'type':'function','function':{'name':'workflow_review','description':'Reviewer only: submit an independent evidence-backed review. Request changes adds a bounded Developer repair before re-review.',
    'parameters':{'type':'object','required':['decision','summary'],'properties':{'decision':{'type':'string','enum':['approved','request_changes']},'summary':{'type':'string','minLength':1,'maxLength':2000}}}}}
TEST_HANDOFF_TOOL = {"type":"function","function":{
    "name":"workflow_test_handoff",
    "description":"Developer only on a missing-test repair step. Declare a real root-level unittest script, its exact command, cwd '.', expected [0], and isolated_cwd true. Does not run commands or grant permission.",
    "parameters":{"type":"object","additionalProperties":False,
        "required":["script","command","cwd","expected_exit_codes","isolated_cwd"],"properties":{
            "script":{"type":"string"},"command":{"type":"string"},"cwd":{"type":"string"},
            "expected_exit_codes":{"type":"array","items":{"type":"integer"}},"isolated_cwd":{"type":"boolean"}}}}}


def test_handoff(root, arguments):
    script = arguments.get("script")
    if not isinstance(script,str) or not re.fullmatch(r"test_[A-Za-z0-9_]{1,80}\.py",script):
        raise ValueError("声明项目根目录下的 test_*.py unittest 脚本")
    command = f"python -m unittest discover -s . -p {script} -v"
    codes = arguments.get("expected_exit_codes")
    if (arguments.get("command") != command or arguments.get("cwd") != "."
            or arguments.get("isolated_cwd") is not True or codes != [0]
            or type(codes[0]) is not int):
        raise ValueError("必须声明精确命令、工作目录 .、预期退出码 [0] 和隔离工作目录")
    path = root / script
    if (not path.is_file() or path.is_symlink() or not path.resolve().is_relative_to(root.resolve())
            or path.stat().st_size > 262144):
        raise ValueError("已声明的测试脚本不存在或超出工作区")
    return {"script":script,"command":command,"cwd":".","expected_exit_codes":[0],
            "isolated_cwd":True,"data_scope":"owned_scratch","script_sha256":hashlib.sha256(path.read_bytes()).hexdigest()}


ROLE_INSTRUCTIONS = {
    'planner': '你是 Planner。使用 read_file、list_directory、search_files、knowledge_search、git_status/git_diff 读取工程、检查约束和依赖；必要时用 workflow_adjust 细化尚未执行步骤的描述、依赖和验收要求。不修改代码。不要运行故障基线测试，也不要运行任意终端脚本；测试属于 Tester。每步包含可验证验收标准。',
    'developer': '你是 Developer。只完成当前步骤的实现或修复，复用已完成操作和真实证据。禁止宣布其他角色已通过。',
    'reviewer': '你是独立 Reviewer。重新读取实际变更并检查需求、兼容性与风险；只读。检查后必须调用 workflow_review 提交 approved 或 request_changes。发现问题必须明确列出，不能仅重复 Developer 的结论。',
    'tester': '你是 Tester。运行当前项目真实测试，检查退出码和日志。不得修改源码、测试或配置以制造通过。环境问题与代码缺陷分开报告。',
}


def normalize_nodes(steps):
    """Validate the entire graph before any write; references use model-local IDs."""
    if not isinstance(steps, list) or not 1 <= len(steps) <= MAX_NODES:
        raise ValueError('工作流必须包含 1..30 个步骤')
    result = []
    for i, source in enumerate(steps):
        node = copy.deepcopy(source)
        ident = node.get('task_id', f'step-{i+1}')
        if not isinstance(ident, str) or not re.fullmatch(r'[\w-]{1,80}', ident):
            raise ValueError('子任务 ID 无效')
        role = node.get('assigned_role', 'developer')
        deps = node.get('dependencies', [] if i == 0 else [result[-1]['task_id']])
        criteria = node.get('acceptance_criteria', [node.get('verification') or '实际工具执行成功并核实结果'])
        capabilities = node.get('required_capabilities', ['tool_calling'])
        for label, value in [('依赖', deps), ('验收标准', criteria), ('能力', capabilities)]:
            if not isinstance(value, list) or len(value) > MAX_NODES or any(not isinstance(x, str) or not x.strip() or len(x)>2000 for x in value):
                raise ValueError(label+'必须为有界字符串列表')
        if role not in ROLES or not criteria:
            raise ValueError('角色或验收标准无效')
        if len(set(deps)) != len(deps):
            raise ValueError('依赖不能重复')
        result.append({'task_id':ident, 'title':str(node.get('title') or node['description'])[:200],
                       'dependencies':deps, 'assigned_role':role,
                       'required_capabilities':capabilities, 'acceptance_criteria':criteria,
                       'retry_count':0})
    ids = [n['task_id'] for n in result]
    if len(set(ids)) != len(ids):
        raise ValueError('子任务 ID 重复')
    pending = {n['task_id']:set(n['dependencies']) for n in result}
    if any(not d <= set(ids) for d in pending.values()):
        raise ValueError('依赖指向不存在的子任务')
    visited = set()
    while pending:
        ready = {k for k,v in pending.items() if v <= visited}
        if not ready:
            raise ValueError('工作流存在循环依赖')
        visited |= ready
        pending = {k:v for k,v in pending.items() if k not in ready}
    return result


def ready_steps(steps):
    done = {s['workflow']['task_id'] for s in steps if s['state'] == 'completed'}
    return sorted([s for s in steps if s['state'] in {'pending','in_progress'}
            and set(s['workflow']['dependencies']) <= done],key=lambda s:s['state']!='in_progress')


def dependency_view(steps):
    """Derived blocking persists through its source states and immutable edges.

    Pending children are never rewritten in SQLite, so repairing a dependency
    automatically makes them ready without replaying or resetting any work.
    """
    blocked={s['workflow']['task_id'] for s in steps if s['state'] in {'blocked','skipped'}}
    while True:
        expanded=blocked|{s['workflow']['task_id'] for s in steps if s['state']=='pending' and set(s['workflow']['dependencies']) & blocked}
        if expanded==blocked:break
        blocked=expanded
    for step in steps:
        reasons=sorted(set(step['workflow']['dependencies']) & blocked)
        if step['state']=='pending' and reasons:
            step.update(state='blocked',dependency_blocked=True,blocked_dependencies=reasons)
    return steps


def progress(steps):
    completed = sum(s['state']=='completed' for s in steps)
    return {'completed':completed, 'total':len(steps),
            'percent':int(100*completed/len(steps)) if steps else 0,
            'blocked':[s['id'] for s in steps if s['state']=='blocked']}


def role_allows(role, tool, arguments, *, read_only=False, allowed_test_hashes=()):
    """Extra restriction, never a grant: normal permissions still apply afterward."""
    if role == 'developer':
        return True
    if tool=='workflow_adjust':return role=='planner'
    if tool == 'workflow_review':
        return role == 'reviewer'
    if tool in {'agent_plan', 'project_memory', 'environment_repair'}:
        return False
    if tool == 'run_command':
        from agent.task_plans import repeatable_check
        command = str(arguments.get('command','')).strip()
        if role == 'tester':
            return repeatable_check(tool, arguments) or hashlib.sha256(command.encode()).hexdigest() in allowed_test_hashes
        return bool(re.fullmatch(r'git\s+(?:diff(?:\s+--check)?|status(?:\s+-sb)?)',command,re.I))
    # Desktop focus/input and arbitrary processes are effects even if their
    # provider metadata advertises them as inspection helpers.
    if tool.startswith('desktop_') or tool in {'start_process','stop_process','read_process'}:
        return False
    return read_only


def scheduling_conflict(left, right):
    """Conservative resource claims; unknown workspace claims serialize."""
    if left.get('gui') and right.get('gui'):
        return 'GUI_FOCUS_CONFLICT'
    if not left.get('workspace') or not right.get('workspace'):
        return 'UNKNOWN_WORKSPACE'
    if left['workspace'] == right['workspace']:
        return 'SHARED_WORKTREE'
    if set(left.get('files',[])) & set(right.get('files',[])):
        return 'SHARED_FILE_WRITE'
    if set(left.get('resources',[])) & set(right.get('resources',[])):
        return 'SHARED_TOOL_RESOURCE'
    return None


def workflow_config(value=None):
    value={} if value is None else value
    if not isinstance(value,dict) or set(value)-{'role_models','max_repairs','max_no_progress','max_parallel'}:
        raise ValueError('工作流配置包含未知字段')
    roles=value.get('role_models',{})
    if not isinstance(roles,dict) or set(roles)-set(ROLES) or any(v is not None and (not isinstance(v,str) or not 1<=len(v)<=200) for v in roles.values()):
        raise ValueError('角色模型配置无效')
    result={'role_models':{r:roles.get(r) for r in ROLES},'max_repairs':value.get('max_repairs',3),'max_no_progress':value.get('max_no_progress',2),'max_parallel':value.get('max_parallel',1)}
    if type(result['max_parallel']) is not int or result['max_parallel'] not in (1,2):
        raise ValueError('最大并行任务数只能为 1 或 2')
    for key in ('max_repairs','max_no_progress'):
        if type(result[key]) is not int or not (0 if key=='max_repairs' else 1)<=result[key]<=10:
            raise ValueError(key+' 必须是有界整数')
    return result


def load_workflow_config(store):
    raw=store.get_setting('workflow.config')
    return workflow_config(json.loads(raw) if raw is not None else None)
