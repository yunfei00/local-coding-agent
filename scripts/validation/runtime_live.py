"""Real providers/tools via the original authenticated HTTP WebSocket entry.

No desktop window; credentials arrive once through an owned anonymous pipe.
This is explicitly not a Windows GUI acceptance test.
"""
from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
import uuid

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from aiohttp import ClientSession,web
from agent.desktop.resources import memory_snapshot,require_resources,MIB
from agent.server.main import AgentServer
from scripts.validation.unified_live import prepare


async def main(manifest,secrets):
    output=Path(manifest['output']);data=Path(manifest['data'])
    if not output.resolve().is_relative_to(ROOT/'validation-reports') or not data.resolve().is_relative_to(ROOT/'validation-reports'):
        raise ValueError('隔离目录边界拒绝')
    report={'result':'RUNNING','controller_stage':'headless_runtime','transport':'production authenticated HTTP WebSocket; no GUI',
        'cases':[],'memory':memory_snapshot(),'models':[],'cost':'UNKNOWN'}
    def save():Path(manifest['report']).write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    threshold=128 if manifest.get('verify_completed') else 512
    save();require_resources(minimum_available=threshold*MIB,minimum_commit=threshold*MIB)
    os.environ['LCA_DATA_DIR']=str(data)
    server=AgentServer(uuid.uuid4().hex)
    server.tasks.credentials.update(secrets.get('credentials',{}));secrets.clear()
    allowed=set(manifest.get('allowed_models') or [])
    if not allowed or any(p['model_id'] not in allowed for p in manifest['profiles']):
        raise ValueError('真实请求必须有正向白名单')
    profiles=manifest['profiles'];primary=next(p for p in profiles if p['model_id']==manifest.get('executor_model',profiles[0]['model_id']))
    peer=next((p for p in profiles if p['model_profile_id']!=primary['model_profile_id']),primary)
    npm_node=shutil.which('node')
    npm_cli=str(Path(npm_node).parent/'node_modules/npm/bin/npm-cli.js') if npm_node else ''
    server.store.set_setting('workflow.config',json.dumps({'role_models':{'planner':peer['model_profile_id'],'reviewer':peer['model_profile_id']}}))
    app=web.Application();app.router.add_get('/ws',server.websocket)
    runner=web.AppRunner(app);await runner.setup();site=web.TCPSite(runner,'127.0.0.1',0);await site.start()
    port=site._server.sockets[0].getsockname()[1]
    async def connect(session):
        ws=await session.ws_connect(f'http://127.0.0.1:{port}/ws',headers={'Authorization':'Bearer '+server.token})
        await ws.receive_json(timeout=15);return ws
    try:
        async with ClientSession() as session:
            ws=await connect(session)
            names=[manifest['resume_case']['name']] if manifest.get('resume_case') else manifest['case_names'] or ['workflow-python']
            for name in names:
                require_resources(minimum_available=threshold*MIB,minimum_commit=threshold*MIB)
                case={'name':name,'result':'RUNNING','tools':[],'models':[]};report['cases'].append(case);save()
                original=manifest.get('resume_case')
                folder=Path(original['folder']) if original else output/(name+'-project')
                if not folder.resolve().is_relative_to(ROOT/'validation-reports'):raise ValueError('工程边界拒绝')
                if not original:
                    prepare(folder)
                    (folder/'.lca').mkdir();(folder/'.lca/verification.json').write_text(json.dumps({'commands':['uv run --no-project python -m unittest discover -s tests -v','git diff --check']}),encoding='utf-8')
                if name=='workflow-react' and not original:
                    shutil.copytree(ROOT/'manual-fixtures/m2-react-ts',folder/'frontend',ignore=shutil.ignore_patterns('node_modules','dist','runtime'))
                    install=await asyncio.create_subprocess_exec(npm_node,npm_cli,'ci',cwd=folder/'frontend',stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.PIPE)
                    out,err=await asyncio.wait_for(install.communicate(),120)
                    case['setup_exit_code']=install.returncode
                    if install.returncode:case.update(result='BLOCKED',reason='FIXTURE_DEPENDENCIES');save();continue
                    (folder/'.lca/verification.json').write_text(json.dumps({'commands':['npm --prefix frontend run typecheck','npm --prefix frontend test','npm --prefix frontend run build','git diff --check']}),encoding='utf-8')
                if not original:
                    for args in (['add','.'],['commit','-qm','Frozen acceptance baseline']):subprocess.run(['git',*args],cwd=folder,capture_output=True,check=True)
                from agent.core.verification import acceptance_snapshot,acceptance_changes
                baseline=acceptance_snapshot(folder)
                project,thread,_=server.projects.open(str(folder),active_model='profile:'+primary['model_profile_id'])
                if original:
                    if original.get('frozen_unchanged') is not True:
                        if not manifest.get('verify_completed'):raise ValueError('旧运行未证明原验收文件未变')
                        for relative in ('tests/test_calc.py','.lca/verification.json'):
                            saved=subprocess.run(['git','show','HEAD:'+relative],cwd=folder,capture_output=True,check=True).stdout
                            # The fixture's Path.write_text uses native Windows
                            # newlines, while Git stores canonical LF blobs.
                            if os.name=='nt':saved=saved.replace(b'\r\n',b'\n').replace(b'\n',b'\r\n')
                            if saved!=(folder/relative).read_bytes():raise ValueError('原始验收文件与 Git 基线不一致')
                        case['frozen_rechecked_against_git_head']=True
                    thread=project.state.get_thread(original['runtime']['plan']['thread_id'])
                    case['completed_before']=[s['id'] for s in original['runtime']['plan']['steps'] if s['state']=='completed']
                    if original.get('reconnect'):case['reconnect']={**original['reconnect'],'evidence_from':manifest['resume_source']}
                case.update(folder=str(folder),usage_before=server.tasks.runtime.usage())
                goal='请使用 workflow_template bugfix，以 Planner/Developer/Reviewer/Tester 四角色修复 calculator.py 的 add 减法错误。保留原测试，Reviewer 重新读取文件并提交 workflow_review，Tester 真实运行 uv run --no-project python -m unittest discover -s tests -v 和 Diff 检查。中文交付，不提交。'
                if name=='workflow-react':goal='请使用 workflow_template feature，实现 frontend React 页面中文加法器：两个 number 输入框 label 为“第一个数”“第二个数”，点击“计算”显示“结果：5”（3+2）。修复现有 TS 类型错误及 math.ts 的加法缺陷；保留原测试、配置及根目录 calculator.py。四角色独立规划、修改、审查并运行 npm --prefix frontend run typecheck、npm --prefix frontend test、npm --prefix frontend run build，中文报告，不提交。'
                if name in {'interruption','websocket'}:goal+=' 计划至少有开发、审查、测试三个分开的执行步骤；不要跳过实际文件修改。'
                if name=='repair':
                    goal+=' Developer 必须先实际运行现有 unittest 得到失败证据，然后定位并修复。实现 add 只接受有限数字，拒绝 bool/字符串/None/NaN/Infinity，新增 unittest 覆盖边界，最后复测。禁止只描述失败或伪造。'
                if name=='environment':
                    (folder/'.lca/verification.json').write_text(json.dumps({'commands':['uv run --no-project python -c "import lca_v09_missing_dependency"']}),encoding='utf-8')
                    baseline=acceptance_snapshot(folder)
                    goal+=' 验收配置故意包含缺失模块；保留配置，报告环境阻断，不安装或无限重试。'
                start={'model':'profile:'+primary['model_profile_id'],'prompt':goal,'unified':True,'background':True}
                if original:start.update(prompt='继续原始任务，只完成未完成步骤，保留全部已完成操作',resume_run_id=original['runtime']['id'],confirm_workspace=True)
                if not manifest.get('verify_completed'):await ws.send_json({'type':'turn.start','thread_id':thread.id,'payload':start})
                deadline=time.monotonic()+650;turn=None;runtime=None;controlled=False;resumed=False;write_seen=False;paused_runtime=None
                while time.monotonic()<deadline:
                    if manifest.get('verify_completed'):break
                    event=await ws.receive_json(timeout=125);kind=event['type'];payload=event.get('payload',{})
                    if kind=='error':case['error']=payload;break
                    if kind=='turn.started':turn=event['turn_id']
                    if kind=='approval.requested':
                        tool=payload['tool'];args=payload.get('arguments',{})
                        from agent.task_plans import repeatable_check
                        safe=tool in {'write_file','apply_patch'} or repeatable_check(tool,args) or (tool=='run_command' and args.get('command')=='uv run --no-project python -c "import lca_v09_missing_dependency"')
                        await ws.send_json({'type':'approval.respond','payload':{'approval_id':payload['approval_id'],'decision':'allow_once' if safe else 'deny'}})
                    if kind=='tool.completed':
                        result=payload.get('result',{});tool=payload.get('name')
                        case['tools'].append({'name':tool,'ok':result.get('ok'),'exit_code':result.get('exit_code'),'call_id':payload.get('tool_call_id')})
                        if tool in {'write_file','apply_patch'} and result.get('ok'):write_seen=True
                    if kind=='agent.runtime.updated':runtime=payload.get('runtime')
                    if kind in {'agent.runtime.updated','tool.completed','model.identity'}:
                        case['runtime']=runtime
                        report['controller_stage']=kind
                        report['usage']=server.tasks.runtime.usage()
                        save()
                    if kind=='plan.step.completed' and write_seen and not controlled and name in {'interruption','websocket'}:
                        controlled=True
                        if name=='interruption':
                            await ws.send_json({'type':'task.runtime.pause','request_id':'pause-control','thread_id':thread.id,'payload':{'run_id':runtime['id']}})
                        else:
                            original_turn=turn;await ws.close();ws=await connect(session)
                            current=server.store.connection.execute('SELECT id,data_json FROM agent_execution_runs WHERE thread_id=? ORDER BY rowid DESC LIMIT 1',(thread.id,)).fetchone()
                            actual=json.loads(current['data_json'])['unified']
                            case['reconnect']={'same_generation':actual['generation']==original_turn,'state':actual['phase'],'replayed_start':False}
                            if actual['phase'] in {'completed','failed','cancelled','paused'}:
                                runtime=actual;break
                    if name=='interruption' and event.get('request_id')=='pause-control' and kind=='task.loaded':
                        paused_runtime=dict(runtime);case['paused_completed_ids']=[s['id'] for s in runtime.get('plan',{}).get('steps',[]) if s['state']=='completed']
                        await ws.send_json({'type':'turn.start','thread_id':thread.id,'payload':{'model':'profile:'+primary['model_profile_id'],'prompt':'继续原任务，保留已完成操作','unified':True,'background':True,'resume_run_id':runtime['id'],'confirm_workspace':True}})
                        resumed=True;continue
                    if kind in {'turn.completed','turn.failed','turn.cancelled'}:
                        if name=='interruption' and controlled and not resumed:continue
                        if event.get('turn_id')==turn:break
                await asyncio.sleep(.05)
                rows=server.store.connection.execute('SELECT id,data_json FROM agent_execution_runs WHERE thread_id=? ORDER BY rowid DESC LIMIT 1',(thread.id,)).fetchall()
                if rows:runtime=json.loads(rows[0]['data_json'])['unified']
                case['runtime']=runtime;case['usage_after']=server.tasks.runtime.usage();case['frozen_unchanged']=not acceptance_changes(folder,baseline)
                if runtime:
                    case['request_events']=[e for e in server.runtime_ledger.events(run_id=runtime['id'],limit=500) if e['kind'].startswith('request.')]
                case['resumed']=resumed;case['roles']=(runtime or {}).get('role_handoffs',[])
                if name=='workflow-react':
                    checks=[]
                    for args in (['run','typecheck'],['test'],['run','build']):
                        proc=await asyncio.create_subprocess_exec(npm_node,npm_cli,*args,cwd=folder/'frontend',stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.PIPE)
                        out,err=await asyncio.wait_for(proc.communicate(),120);checks.append({'command':'npm '+' '.join(args),'exit_code':proc.returncode,'summary':(out+err).decode('utf-8','replace')[-2000:]})
                    case['independent']=checks
                    passed=all(c['exit_code']==0 for c in checks)
                else:
                    proc=await asyncio.create_subprocess_exec('uv','run','--no-project','python','-m','unittest','discover','-s','tests','-v',cwd=folder,stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.PIPE)
                    out,err=await asyncio.wait_for(proc.communicate(),60)
                    case['independent']={'exit_code':proc.returncode,'summary':(out+err).decode('utf-8','replace')[-2500:]};passed=proc.returncode==0
                roles_ok=all(any(h['role']==role for h in case['roles']) for role in ('planner','developer','reviewer','tester'))
                case['result']='PASS' if runtime and runtime.get('outcome')=='completed_verified' and passed and case['frozen_unchanged'] and roles_ok else 'FAIL'
                if original and not all(any(s['id']==ident and s['state']=='completed' for s in runtime['plan']['steps']) for ident in case['completed_before']):case['result']='FAIL'
                if name=='interruption' and not (resumed and case.get('paused_completed_ids') and all(any(s['id']==ident and s['state']=='completed' for s in runtime['plan']['steps']) for ident in case['paused_completed_ids'])):case['result']='FAIL'
                if name=='websocket' and not case.get('reconnect',{}).get('same_generation'):case['result']='FAIL'
                if name=='environment':case['result']='PASS' if runtime and runtime.get('outcome')=='awaiting_user' and runtime.get('validation_blocked') and any(r.get('category')=='environment' for r in runtime.get('verification',[])) and runtime.get('repairs',0)==0 and case['frozen_unchanged'] else 'FAIL'
                if name=='repair' and not any(t['name']=='run_command' and t['ok'] is False and t['exit_code'] not in (0,None) for t in case['tools']):case.update(result='FAIL',reason='未观察到 Agent 自己执行的失败测试，不能声称修复闭环通过')
                save()
            await ws.close()
        report['usage']=server.tasks.runtime.usage();report['result']='PASS' if report['cases'] and all(c['result']=='PASS' for c in report['cases']) else 'PARTIAL'
        save()
    finally:
        await server.close_async();server.close();await runner.cleanup()
    return 0 if report['result']=='PASS' else 1


if __name__=='__main__':
    manifest=json.loads(Path(sys.argv[1]).read_text(encoding='utf-8'))
    secrets={} if manifest.get('verify_completed') else json.loads(sys.stdin.readline())
    try:sys.exit(asyncio.run(main(manifest,secrets)))
    except Exception as exc:
        # No exception message: provider/OS failures may contain secrets.
        p=Path(manifest['report']);r=json.loads(p.read_text(encoding='utf-8')) if p.exists() else {}
        import traceback,re
        r.update(result='BLOCKED',error_code=getattr(exc,'code',type(exc).__name__),
            traceback=[{'file':Path(f.filename).name,'line':f.lineno,'function':f.name} for f in traceback.extract_tb(exc.__traceback__)][-8:])
        if isinstance(exc,KeyError) and exc.args and re.fullmatch(r'[a-zA-Z0-9_.-]{1,80}',str(exc.args[0])):r['missing_field']=str(exc.args[0])
        p.write_text(json.dumps(r,ensure_ascii=False,indent=2),encoding='utf-8')
        print('Headless runtime validation BLOCKED; see sanitized report.');sys.exit(1)
