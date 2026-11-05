"""Evidence-based delivery artifacts; never commits, pushes or publishes."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from agent.core.diagnostics import redact_text


def build_delivery(goal, runtime, plan, reviews, calls):
    tests=[{k:r.get(k) for k in ('command','ok','exit_code','category','summary','log_path','duration_ms')}
           for r in runtime.get('verification',[])]
    steps=[{'id':s['id'],'description':s['description'],'state':s['state'],
            'role':s.get('workflow',{}).get('assigned_role'), 'evidence':s.get('evidence',[])}
           for s in (plan or {}).get('steps',[])]
    verified=bool(tests) and all(t['ok'] is True and t['exit_code']==0 for t in tests)
    complete=all(s['state']=='completed' for s in steps)
    status='已完成且验证通过' if complete and verified else '部分完成或验收未通过'
    title='自主开发交付：'+goal.replace('\n',' ')[:120]
    report={'goal':goal,'status':status,'changed_files':runtime.get('changed_paths',[]),
            'steps':steps,'tests':tests,'reviews':reviews,'model_calls':calls,
            'model_usage':runtime.get('usage',{}),'model_event_tail_limit':500,
            'git':runtime.get('git_delivery',{'available':False,'reason':'未获取 Git Diff 证据'}),
            'limits':['模型文字不能代替工具证据','未自动 Commit、Push、合并或发布'],
            'unfinished':[s['id'] for s in steps if s['state']!='completed'],
            'reason':runtime.get('reason',''),'pr_draft':{'title':title,'body':'请审阅实际 Diff、下列验证证据和未完成事项；本报告没有创建远程 PR。'}}
    lines=['# 自主任务交付报告','',f'结论：{status}','', '## 用户目标','',goal,'','## 修改文件','']
    lines += ['- '+p for p in report['changed_files']] or ['未检测到修改文件。']
    lines += ['','## 独立验证','']
    lines += [f"- {'PASS' if t['ok'] and t['exit_code']==0 else 'FAIL/BLOCKED'}：{t['command']}；exit {t['exit_code']}；日志 {t['log_path']}" for t in tests] or ['未执行自动验证，不能声称通过。']
    lines += ['','## 角色与执行证据','']
    lines += [f"- {s['role'] or '原执行角色'}：{s['description']}；{s['state']}；工具证据 {len(s['evidence'])} 项" for s in steps]
    lines += ['','## 独立审查','']+[f"- {r['decision']}：{r['summary']}" for r in reviews]
    lines += ['','## 风险与未完成事项','',report['reason'] or '详见实际测试与 Diff；未自动执行 Git 交付操作。',
              '未完成步骤：'+(', '.join(report['unfinished']) or '无未完成计划步骤'),'']
    return report,'\n'.join(lines)


def write_delivery(directory, run_id, report, markdown, *, exact_secrets=()):
    root=Path(directory);root.mkdir(parents=True,exist_ok=True)
    stem=hashlib.sha256(run_id.encode()).hexdigest()[:32]
    outputs={}
    def clean(value):
        if isinstance(value,str):return redact_text(value,exact_secrets=exact_secrets,max_chars=12000)
        if isinstance(value,dict):return {key:clean(item) for key,item in value.items()}
        if isinstance(value,list):return [clean(item) for item in value]
        return value
    for extension,content in [('json',json.dumps(clean(report),ensure_ascii=False,indent=2)),('md',redact_text(markdown,exact_secrets=exact_secrets,max_chars=200000))]:
        path=root/(stem+'.'+extension)
        temp=path.with_suffix(path.suffix+'.tmp')
        temp.write_text(content,encoding='utf-8')
        temp.replace(path)
        outputs[extension+'_path']=str(path)
    return outputs
