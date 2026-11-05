"""Policy and result metadata for the existing loop; no executor or state machine."""
from __future__ import annotations

import json
import os
import base64
import time
import hashlib
import re
from pathlib import Path

from agent.core.verification import discover_commands
from agent.llm.planning import PLAN_SCHEMA, validate_plan

PLAN_TOOL = {"type": "function", "function": {
    "name": "agent_plan", "description": "Persist a cohesive plan for complex, multi-module development. Do not use for questions or small edits. Does not execute files or grant permissions.",
    "parameters": PLAN_SCHEMA}}
INSTRUCTIONS = """Unified Agent: infer intent from the user's goal, repository context and actual tools, not keywords.
Answer ordinary questions directly, with no tools or plan. Analyze using relevant read-only tools; do not edit without a change request.
For a small change use normal tools directly. For complex multi-file development call agent_plan with 1-4 cohesive executable steps before editing.
Keep each tool batch small: create a short file skeleton then apply small focused patches (about 80 lines per edit). Do not emit an entire multi-file project in one tool response; each response must finish within the configured request timeout.
Each step must have real tool evidence; avoid prose-only steps. Use an empty verification for edit/inspection steps, a concrete command for test steps.
Do not ask the user to choose chat/development modes. You may upgrade a small task using agent_plan, preserving all existing changes and evidence.
After code changes the runtime independently runs verification. Never claim tests passed without actual exit-code evidence.
For project questions use knowledge_search to retrieve actual paths/lines and read the relevant files. project_memory may search or save concise candidate knowledge, never raw chat or secrets. Candidate memory is unverified; current code and real test evidence take priority. Do not overwrite user rules. environment_diagnose performs read-only checks; environment_repair always requires the existing approval and a real re-check. Never modify global settings to hide environment errors.
Keep the final report in Chinese, including changed files, actual verification and unresolved issues. Environment failures must not cause endless retries.
For Windows computer tasks discover and authorize the exact window, focus it, then inspect live UIA controls. Verify actual state after actions; do not confuse a request being sent with its effect being verified.
Only when UIA cannot locate/invoke the target, request an authorized screenshot for a vision-capable model. Use desktop_click method=coordinate, coordinate_space=model_image, artifact_id from that capture and its image-pixel x/y, with fresh confirm_risk approval. Do not guess coordinates, read source code to bypass the interface, or fallback after a privacy/approval/session denial. Re-capture after movement, resizing or stale capture errors.
Ordinary editable controls use exact selectors. RichEdit Document controls require confirm_risk and verified text readback; webpage Document or arbitrary Pane is not an editor.
Windows app activation can reuse a process/window: use a unique task-owned file/window and actual discovery, not an assumed launcher PID. Never terminate a pre-existing user application. On BLOCKED_RESOURCE stop launching GUI processes; preserve progress and continue unrelated checks.
"""


def plan_steps(value):
    return validate_plan(value)


def plan_view(plan):
    """Never embed the execution ledger back into its own runtime snapshot."""
    return {key:value for key,value in plan.items() if key!='execution'}


def memory_authorization_text(prompt):
    text=re.sub(r'(?s)```.*?(?:```|$)|~~~.*?(?:~~~|$)','',prompt)
    return '\n'.join(line for line in text.splitlines() if not line.lstrip().startswith('>'))

def explicit_memory_rules(prompt):
    return re.findall(r'(?:^|[。；;\n])\s*(?:请)?记住[:：]\s*([^\r\n]{1,1500})',memory_authorization_text(prompt))[:12]

def requested_intent(prompt):
    """Conservative request-shape fallback; model plans and tool evidence refine it."""
    paths=set(re.findall(r'[\w./\\-]+\.(?:py|tsx?|jsx?|json|toml|ya?ml|md)\b',prompt,re.I))
    text=re.sub(r'[\w./\\-]+\.(?:py|tsx?|jsx?|json|toml|ya?ml|md)\b',' FILE ',prompt,flags=re.I)
    readonly=bool(re.search(r'只分析|仅分析|只读|(?:不|不要|禁止|不得)(?:修改|改动|编辑)(?:任何)?(?:代码|源码|文件|工程)|不(?:读取或)?修改工程|本轮只分析|do not (?:edit|modify) (?:any )?(?:files|code)',text,re.I))
    question=bool(re.search(r'^\s*(?:请)?(?:解释|讲解|如何|怎么|什么|只回答|仅回答|只返回|仅返回|what\b|how\b|why\b|explain\b)|是什么|什么意思',text,re.I))
    direct=bool(re.search(r'(?:请|帮我|直接|现在)(?:实现|开发|修复|修改|重构|新增)|can you (?:add|fix|implement|create|change)',text,re.I))
    change=not readonly and bool(re.search(r'实现|开发|修复|修改|重构|新增|增加|改成|改为|改中文|编写|创建|\b(?:implement|develop|refactor|create|fix|add|change|update)\b',text,re.I)) and (not question or direct)
    listed=len(re.findall(r'(?m)^\s*(?:\d+[.)、]|[-*])\s*\S',prompt))
    kind='question' if question and not direct else 'complex' if change and (listed>=3 or len(paths)>=3) else 'change' if change else 'analysis' if readonly or re.search(r'分析|诊断|检查|inspect|analy[sz]e|diagnos',text,re.I) else 'question'
    positive=re.sub(r'(?:禁止|不要|不得|不允许|不(?:修改|改动|编辑))[^。；;\n]*','',text)
    code_request=bool(re.search(r'开发|实现|编写|重构|修复|源码|代码|组件|函数|模块|\b(?:develop|implement|refactor|fix|function|component)\b',positive,re.I)) or (change and bool(re.search(r'\bFILE\b',positive)))
    analysis_only=bool(re.search(r'只分析|仅分析|只读|本轮只分析|analysis only|only analy[sz]e',text,re.I))
    interaction=not analysis_only and not question and not code_request and bool(re.search(r'(?:桌面|窗口|界面|Settings|Display name).*(?:输入|点击|键入|填写)|(?:click|type|enter).*(?:button|window|settings|field)',positive,re.I|re.S))
    if interaction:kind='interaction'
    environment_write=not question and not analysis_only and bool(re.search(r'environment_repair|(?:修复|恢复|重置).{0,16}(?:环境|PATH|代理|依赖)|(?:环境|PATH|代理|依赖).{0,16}(?:修复|恢复|重置)',positive,re.I))
    code_edit=bool(re.search(r'(?:修复|修改|开发|实现|重构).{0,16}(?:代码|源码|函数|组件)',positive)) or (change and any(not p.lower().endswith(('.md','.json','.toml','.yaml','.yml')) for p in paths))
    environment_write=environment_write and not code_edit and not interaction
    if environment_write:kind='analysis';readonly=True
    project_question=bool(re.search(r'(?:本|当前|这个|该|this)\s*(?:项目|工程|仓库|程序|模块|文件|project|repo)|(?:分析|解释|检查).{0,8}(?:项目|工程|仓库|程序)',text,re.I))
    if kind=='question' and (project_question or paths):kind='analysis'
    memory_write=bool(re.search(r'记住|保存.{0,20}(?:知识|记忆|约定)|(?:知识|记忆).{0,12}保存|remember|save.{0,20}memor',memory_authorization_text(prompt),re.I))
    return {'kind':kind,'read_only':kind!='interaction' and (readonly or kind=='analysis' or (question and not direct)),'pure_question':kind=='question' and question and not project_question and not paths and not memory_write,'memory_write':memory_write,'environment_write':environment_write,'referenced_files':len(paths),'listed_steps':listed}


COMPUTER_TOOLS={'start_process','read_process','stop_process','list_directory','file_exists','agent_plan',*('desktop_'+n for n in ('list_windows','inspect','screenshot','focus_window','click','type_text','keypress','scroll','wait'))}

def computer_only(goal):
    """明确的仅界面授权边界，不改变普通代码/分析任务的工具范围。"""
    return requested_intent(goal)['kind']=='interaction' and bool(re.search(r'只操作界面|仅(?:限)?(?:界面|桌面)操作|禁止读取.{0,24}(?:源码|HTML|JS)',goal,re.I))


def infer_intent(previous, tool, *, changed_paths=(), read_only=False, operations=0):
    if previous == "complex" or tool == "agent_plan" or len(set(changed_paths)) >= 3 or (operations >= 12 and changed_paths):
        return "complex"
    if changed_paths or previous == "change":
        return "change"
    if previous=='interaction' or tool in {'desktop_click','desktop_type_text','desktop_keypress','desktop_scroll'}:
        return 'interaction'
    return "analysis" if read_only or tool else previous or "question"


def workspace_snapshot(root):
    """Bounded metadata plus safe-source digests; never persist file contents."""
    from agent.core.project_files import ProjectFiles,EXTENSIONS,MAX_BYTES
    root=Path(root).resolve()
    policy=ProjectFiles(root);result={};hashed_bytes=0
    excluded = {'.git','.runtime','node_modules','.venv','venv','__pycache__','.pytest_cache','.mypy_cache','.ruff_cache','dist','build','release','coverage','validation-reports'}
    for directory, dirs, files in os.walk(root,followlinks=False):
        dirs[:] = [d for d in dirs if d not in excluded and not d.lower().endswith(('.egg-info','.dist-info')) and not (Path(directory)/d).is_symlink()]
        for name in files:
            path = Path(directory)/name
            if path.is_symlink():
                continue
            try:
                stat = path.stat()
                signature=[stat.st_size,stat.st_mtime_ns]
                if path.suffix.lower() in EXTENSIONS and stat.st_size<=MAX_BYTES and policy.allowed(path):
                    if hashed_bytes+stat.st_size<=8*1024*1024:
                        hashed_bytes+=stat.st_size
                        content=policy.read(path)
                        if content is not None:signature.append(hashlib.sha256(content.encode()).hexdigest())
                    else:result['.lca-snapshot-incomplete']=[-1,-1]
                result[path.relative_to(root).as_posix()]=signature
            except OSError:
                continue
            if len(result) >= 20000:
                result['.lca-snapshot-incomplete']=[-1,-1]
                return result
    return result

def changed_since_snapshot(before,after):
    """Preserve legacy two-field checkpoints; compare new source hashes over timestamps."""
    changed=set()
    for path in set(before)|set(after):
        if any(part.lower().endswith(('.egg-info','.dist-info')) for part in Path(path).parts):continue
        old,new=before.get(path),after.get(path)
        if old is None or new is None:changed.add(path)
        elif len(old)>2:
            if len(new)<3 or old[0]!=new[0] or old[2]!=new[2]:changed.add(path)
        elif old[:2]!=new[:2]:changed.add(path)
    return changed

def snapshot_fingerprint(snapshot):
    return json.dumps({p:[v[0],v[2]] if len(v)>2 else v for p,v in snapshot.items()},sort_keys=True)


class RuntimeEvents:
    """Observe terminal evidence from the original loop, without hiding or replacing events."""
    def __init__(self, ws, execution, runtime):
        self.ws,self.execution,self.runtime=ws,execution,runtime

    async def send_json(self,event):
        if event['type'] in {'turn.failed','turn.cancelled'}:
            payload=event.get('payload',{})
            disconnected=payload.get('reason')=='connection_interrupted' or payload.get('code')=='CONNECTION_INTERRUPTED'
            values=dict(phase='paused' if disconnected else 'cancelled' if event['type']=='turn.cancelled' else 'failed',
                outcome='awaiting_user' if disconnected else 'cancelled' if event['type']=='turn.cancelled' else 'awaiting_user' if payload.get('code') in {'PLAN_RESUME_CONFIRMATION_REQUIRED','APPROVAL_DENIED','PERMISSION_DENIED'} else 'partially_completed' if self.runtime.get('changed_paths') else 'failed',
                reason=str(self.runtime.get('reason') if disconnected else payload.get('message') or payload.get('reason') or payload.get('code') or '执行停止')[:2000],
                error_code=payload.get('code'))
            if self.execution.ledger:
                phase=values.pop('phase')
                if self.execution.ledger.transition(self.execution,phase,event.get('turn_id'),**values) is None:
                    return
            else:
                self.runtime.update(values)
                self.execution.save()
        await self.ws.send_json(event)


def export_diagnostics(root, owner, data, plans, *, exact_secrets=(), ledger=None):
    """Small transport response; complete filtered evidence stays in local files."""
    from agent.core.diagnostics import redact_text
    runtime=data['unified']
    plan=plan_view(plans.get(runtime['plan_id'])) if runtime.get('plan_id') else None
    def safe(value):
        if isinstance(value,str):return redact_text(value,exact_secrets=exact_secrets,max_chars=2000)
        if isinstance(value,list):return [safe(x) for x in value]
        if isinstance(value,dict):return {k:safe(v) for k,v in value.items() if k not in {'stdout','stderr','goal','prompt','content','arguments','unified_baseline'}}
        return value
    history=safe({'runtime':runtime,'requests':data.get('unified_api_requests',[]),'verification_history':data.get('unified_verification_history',[]),'executions':plans.executions(plan['id']) if plan else [],'plan':plan})
    rows=['# 当前 Agent 诊断',f'运行：{owner}',f"阶段：{runtime['phase']}",f"结果：{runtime.get('outcome') or '执行中'}",f"当前原因：{safe(runtime.get('reason') or runtime.get('error_code') or '没有当前错误')}"]
    if runtime.get('active_tool'):
        rows.extend(['当前/中断工具：'+safe(runtime['active_tool'].get('name','')), '命令：'+safe(runtime['active_tool'].get('command','')), '退出码：未确认', '本轮验证日志目录：'+safe(runtime.get('verification_log_root',''))])
    for result in runtime.get('verification',[])[:12]:
        rows.extend([f"- 命令：{safe(result.get('command',''))}",f"  exit {result.get('exit_code')} / {result.get('category')}",f"  日志：{safe(result.get('log_path') or '无命令执行日志')}",f"  摘要：{safe(result.get('summary',''))[-400:]}"])
    for result in runtime.get('diagnostic_checks',[])[-6:]:
        rows.extend([f"- 只读诊断命令：{safe(result['command'])}",f"  exit {result['exit_code']}（失败是分析证据，不代表测试通过）",safe(result.get('summary',''))[-400:]])
    if plan:
        rows.append('未完成步骤：')
        rows.extend(f"- {s['id']} / {s['state']} / {safe(s['description'])[:160]}" for s in plan['steps'] if s['state'] not in {'completed','skipped'})
    if ledger:
        rows.append('最近请求/执行事件：')
        for event in ledger.events(run_id=owner,limit=12):
            meta=event['metadata']
            rows.append(f"- {event['label']} / {event.get('request_id') or event['event_id']} / HTTP {meta.get('http_status')} / 已发送 {meta.get('request_sent')} / {meta.get('error_code') or ''}")
    markdown='\n'.join('\n'.join(rows).splitlines()[:140])+'\n\n完整请求与工具证据见同目录 JSON；原始日志和数据库历史未删除。\n'
    root.mkdir(parents=True,exist_ok=True)
    stem=hashlib.sha256(owner.encode()).hexdigest()[:24]
    full=root/(stem+'.json');short=root/(stem+'.md')
    if ledger:
        events=root/(stem+'-events.json')
        history['request_events_path']=str(events)
        history['request_events_count']=ledger.export_run(events,owner)
        history['recent_request_events']=ledger.events(run_id=owner,limit=40)
    full.write_text(json.dumps(history,ensure_ascii=False,indent=2),encoding='utf-8')
    short.write_text(markdown,encoding='utf-8')
    return {'markdown':markdown,'json_path':str(full),'markdown_path':str(short),'history_source':'existing execution ledger and TaskPlanStore; no history removed'}


def verification_policy(root: Path, paths, configured=(), override="auto"):
    """Bounded discovery, only existing project capabilities. Commands still require approval."""
    root=root.resolve()  # Windows TEMP may use an 8.3 alias while children resolve to long paths.
    if override not in {"auto", "none", "basic", "targeted", "full", "manual"}:
        raise ValueError("Invalid unified verification level")
    paths = sorted(set(str(p).replace("\\", "/") for p in paths))
    if not paths:
        return {"level": "none", "commands": [], "reason": "No file change requires validation"}
    if any(not (root/name).resolve().is_relative_to(root.resolve()) for name in paths):
        raise ValueError('Changed paths outside the project require separate manual validation')
    if override in {"none", "manual"}:
        return {"level": override, "commands": [], "reason": "Explicit verification preference; development remains unverified"}
    explicit=bool(configured) or (root/'.lca/verification.json').exists()
    if explicit and override!='basic':
        commands=discover_commands(root,list(configured))
        return {'level':'full' if override=='full' else 'targeted','commands':commands,'reason':'Explicit project verification commands'}
    packages={}
    frontend={'.ts','.tsx','.js','.jsx','.css','.html','.json'}
    for name in paths[:200]:
        path=(root/name).resolve()
        if path.suffix.lower() not in frontend:continue
        for parent in (path.parent,*path.parents):
            if not parent.is_relative_to(root.resolve()):break
            manifest=parent/'package.json'
            if manifest.is_file():
                if not manifest.resolve().is_relative_to(root.resolve()) or manifest.stat().st_size>100000:
                    raise ValueError('Unsafe verification manifest')
                prefix=parent.relative_to(root).as_posix()
                # Quoted shell paths must contain no expansion/quote characters.
                # Exotic folder names require explicit, reviewed project commands.
                if not re.fullmatch(r'[\w ./-]+',prefix):
                    raise ValueError('Automatic verification refuses shell-special package paths; configure explicit project verification')
                value=json.loads(manifest.read_text(encoding='utf-8-sig'))
                scripts=value.get('scripts',{}) if isinstance(value,dict) else None
                if not isinstance(scripts,dict) or any(not isinstance(k,str) or not isinstance(v,str) for k,v in scripts.items()):
                    raise ValueError('package.json scripts must be an object of command strings')
                entry=packages.setdefault(prefix,{'root':parent,'scripts':scripts,'typed':False})
                entry['typed'] |= path.suffix.lower() in {'.ts','.tsx'}
                break
    package_commands=[]
    for prefix,entry in packages.items():
        npm='npm '+('--prefix '+json.dumps(prefix,ensure_ascii=False)+' ' if prefix!='.' else '')
        scripts=entry['scripts']
        package_commands.extend(npm+'run '+name for name in ('typecheck','test','build') if name in scripts)
        if entry['typed'] and 'typecheck' not in scripts and override!='basic':
            compiler=entry['root']/'node_modules/typescript/bin/tsc'
            config=entry['root']/'tsconfig.json'
            if compiler.is_file() and config.is_file():
                compiler_path=compiler.relative_to(root).as_posix()
                config_path=config.relative_to(root).as_posix()
                package_commands.insert(0,'node '+json.dumps(compiler_path,ensure_ascii=False)+' --noEmit -p '+json.dumps(config_path,ensure_ascii=False))
            else:
                return {'level':'manual','commands':[],'reason':'TypeScript changes require a declared typecheck script or installed project TypeScript compiler and tsconfig; type checking was not run'}
    if len(package_commands)>12:
        return {'level':'manual','commands':[],'reason':'Affected packages exceed 12 validation commands; configure an integration command'}
    has_python=any(name.endswith('.py') for name in paths)
    if override!='basic':
        root_commands=discover_commands(root,[])
        if package_commands and not has_python and override!='full':
            commands=package_commands
        else:
            commands=root_commands+package_commands
        commands=list(dict.fromkeys('uv run --no-project '+c if c.startswith('python ') and not (root/'pyproject.toml').exists() else c for c in commands))
        if commands:
            if (root/'.git').exists() and 'git diff --check' not in commands:commands.append('git diff --check')
            modules=[name for name in paths if name.endswith('.py') and not name.startswith('tests/') and not Path(name).name.startswith('test_')]
            full=override=='full' or len(packages)>1 or (has_python and bool(package_commands)) or len(modules)>1 or len(paths)>=8
            return {'level':'full' if full else 'targeted','commands':commands,'reason':'Available project checks for the affected languages/packages'}
    python_files = [p for p in paths if p.endswith(".py") and (root / p).is_file()]
    json_files = [p for p in paths if p.endswith(".json") and (root / p).is_file()]
    # Explicit interpreter commands parse syntax without importing/executing project files.
    checks = []
    prefix = "uv run python" if (root / "pyproject.toml").is_file() else "uv run --no-project python"
    for p in python_files[:30]:
        encoded = base64.b64encode(p.encode()).decode()
        checks.append(prefix + ' -c "import ast,base64,pathlib; ast.parse(pathlib.Path(base64.b64decode(\''+encoded+'\').decode()).read_text(encoding=\'utf-8-sig\'))"')
    for p in json_files[:30]:
        encoded = base64.b64encode(p.encode()).decode()
        checks.append(prefix + ' -c "import json,base64,pathlib; json.loads(pathlib.Path(base64.b64decode(\''+encoded+'\').decode()).read_text(encoding=\'utf-8-sig\'))"')
    return {"level": "basic" if checks else "manual", "commands": checks,
            "reason": "Syntax/config checks only; no project tests discovered" if checks else "No applicable automated validation found"}


def result_view(*, changed, results, status="completed", pending=False, level="none"):
    if status == "cancelled":
        return "cancelled"
    if status == "failed":
        return "failed"
    if pending:
        return "partially_completed"
    if (changed and level == 'manual') or any(not r.get("ok") and r.get("category") in {"environment", "configuration", "network", "permission", "timeout", "cancelled"} for r in results):
        return "awaiting_user"
    if changed and (not results or any(not r.get("ok") for r in results) or level in {"none", "manual"}):
        return "completed_unverified"
    return "completed_verified" if changed else "completed_unverified" if results and any(not r.get("ok") for r in results) else "completed_verified"
