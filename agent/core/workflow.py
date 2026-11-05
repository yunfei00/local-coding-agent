"""DAG metadata and role policy for the existing TaskPlanStore/Agent loop.

No model client, tool executor or alternate execution loop lives here.
"""
from __future__ import annotations

import copy
import re

ROLES = ('planner', 'developer', 'reviewer', 'tester')
MAX_NODES = 30
REVIEW_TOOL = {'type':'function','function':{'name':'workflow_review','description':'Reviewer only: submit an independent evidence-backed review. Request changes adds a bounded Developer repair before re-review.',
    'parameters':{'type':'object','required':['decision','summary'],'properties':{'decision':{'type':'string','enum':['approved','request_changes']},'summary':{'type':'string','minLength':1,'maxLength':2000}}}}}
ROLE_INSTRUCTIONS = {
    'planner': '你是 Planner。读取工程、检查约束和依赖；不修改代码。每步包含可验证验收标准。',
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
    return [s for s in steps if s['state'] in {'pending','in_progress'}
            and set(s['workflow']['dependencies']) <= done]


def progress(steps):
    completed = sum(s['state']=='completed' for s in steps)
    return {'completed':completed, 'total':len(steps),
            'percent':int(100*completed/len(steps)) if steps else 0,
            'blocked':[s['id'] for s in steps if s['state']=='blocked']}


def role_allows(role, tool, arguments, *, read_only=False):
    """Extra restriction, never a grant: normal permissions still apply afterward."""
    if role == 'developer':
        return True
    if tool == 'workflow_review':
        return role == 'reviewer'
    if tool in {'agent_plan', 'project_memory', 'environment_repair'}:
        return False
    if tool == 'run_command':
        from agent.task_plans import repeatable_check
        command = str(arguments.get('command','')).strip()
        if role == 'tester':
            return repeatable_check(tool, arguments)
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
