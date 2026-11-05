"""Data-driven plans consumed by agent_plan in the original unified loop."""
from __future__ import annotations

import json
from pathlib import Path

from agent.core.workflow import normalize_nodes

TEMPLATE_PATH = Path(__file__).with_name('workflow_templates.json')


def load_templates(custom=()):
    templates=json.loads(TEMPLATE_PATH.read_text(encoding='utf-8'))
    if not isinstance(custom,(list,tuple)) or len(custom)>20:
        raise ValueError('自定义模板最多 20 项')
    seen=set()
    for template in [*templates,*custom]:
        if not isinstance(template,dict) or not isinstance(template.get('id'),str) or template['id'] in seen:
            raise ValueError('模板 ID 无效或重复')
        if set(template)-{'id','name','applies_to','steps','permissions','failure_policy'}:
            raise ValueError('模板包含未知字段')
        seen.add(template['id'])
        normalize_nodes(template['steps'])
    return [*templates,*custom]


def expand_template(ident, parameters=None, *, custom=()):
    parameters={} if parameters is None else parameters
    if not isinstance(parameters,dict) or set(parameters)-{'goal','verification_command'}:
        raise ValueError('只支持 goal、verification_command 参数')
    if any(not isinstance(v,str) or len(v)>4000 for v in parameters.values()):
        raise ValueError('模板参数必须是有界文本')
    template=next((t for t in load_templates(custom) if t['id']==ident),None)
    if template is None:raise ValueError('模板不存在')
    result=json.loads(json.dumps(template))
    for step in result['steps']:
        step['description']=step['description']+('；目标：'+parameters['goal'] if parameters.get('goal') else '')
        if step['assigned_role']=='tester' and parameters.get('verification_command'):
            step['verification']=parameters['verification_command']
    # Strings are never executed by this expansion; original tool approvals
    # authorize each eventual command, including customized verification.
    normalize_nodes(result['steps'])
    return result


TEMPLATE_TOOL={'type':'function','function':{'name':'workflow_template','description':'Load a reusable evidence-backed plan for complex work; does not execute commands or grant permission. Available: bugfix, feature, review, tests, environment, windows, docs, package.',
    'parameters':{'type':'object','required':['template_id'],'properties':{'template_id':{'type':'string'},'parameters':{'type':'object','properties':{'goal':{'type':'string'},'verification_command':{'type':'string'}}}}}}}
