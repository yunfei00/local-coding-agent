"""Explicit bounded live acceptance through the production Electron IPC; never decrypts keys."""
import argparse
import hashlib
import json
import os
import sqlite3
import shutil
from pathlib import Path
import subprocess
import sys
from urllib.parse import urlsplit

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from scripts.validation.real_online_agent_e2e import load_catalog,run_controller
from agent.persistence.store import SQLiteStore
from agent.core.model_catalog import KEY
from agent.llm.router import validate_config


def controller_result(code, report_path):
    """控制器正常退出不等于验收通过；BLOCKED/PARTIAL 不返回成功。"""
    if code:
        return code
    try:
        result=json.loads(report_path.read_text(encoding='utf-8')).get('result')
    except (OSError,ValueError):
        return 1
    return 0 if result=='PASS' else 1


def prepare(root):
    root.mkdir(parents=True,exist_ok=False)
    (root/'calculator.py').write_text('def add(a,b):\n    return a-b\n',encoding='utf-8')
    (root/'tests').mkdir()
    (root/'tests/test_calc.py').write_text('import unittest\nfrom calculator import add\nclass Calc(unittest.TestCase):\n def test_add(self): self.assertEqual(add(3,2),5)\n',encoding='utf-8')
    (root/'.gitignore').write_text('__pycache__/\n.venv/\n',encoding='utf-8')
    for args in (['init','-q'],['config','user.name','LCA validation'],['config','user.email','validation@example.test'],['add','.'],['commit','-qm','Synthetic acceptance baseline']):
        subprocess.run(['git',*args],cwd=root,capture_output=True,check=True)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--live',action='store_true')
    parser.add_argument('--allowed-model',action='append',default=[],help='本轮正向模型白名单；原始配置不变，别名不自动放行')
    parser.add_argument('--installed-executable',type=Path,help='实际安装的 Windows 应用，不能计为干净系统验收')
    parser.add_argument('--full-access',action='store_true',help='本轮隔离工程明确授权完全访问；不修改原用户配置')
    parser.add_argument('--suite',action='store_true')
    parser.add_argument('--headless-runtime',action='store_true',help='无桌面窗口，通过同一后端认证 WebSocket 验收；不能计为 GUI PASS')
    parser.add_argument('--isolate-git-path',action='store_true',help='仅本轮 Electron/Agent 子进程移除 Git PATH，保留父进程及用户配置')
    parser.add_argument('--automatic-routing',action='store_true',help='真实聊天选择自动模型，候选来自本轮实际能力探针')
    parser.add_argument('--reopen-memory-report',type=Path,help='仅重启本仓库隔离目录内的记忆验收，不读写用户数据')
    parser.add_argument('--case',action='append',choices=['question','analysis','change','python-smoke','react','electron','gui','visual','approval','network','followup','coupon','environment','repair','context','interruption','websocket','json','project-memory','memory-reopen','knowledge-fix','environment-repair','environment-git','environment-python','routing','workflow-python','workflow-react','native-gui','revocation'],default=[])
    parser.add_argument('--request-seconds',type=int,default=60)
    parser.add_argument('--output-tokens',type=int,default=8192)
    parser.add_argument('--validation-task-calls',type=int,help='用户授权的隔离验收任务请求上限，不修改原 Settings')
    parser.add_argument('--validation-task-tokens',type=int,help='用户授权的隔离验收任务 Token 上限，不修改原 Settings')
    parser.add_argument('--reuse-capabilities',type=Path,help='Reuse this session capability evidence; actual Agent cases still run')
    parser.add_argument('--discover-only',action='store_true',help='List provider model IDs over the existing connection; no generation')
    parser.add_argument('--capabilities-only',action='store_true',help='只探测实际模型能力，不启动 Agent 工程用例')
    parser.add_argument('--vision-candidate-model',action='append',default=[],help='仅在隔离验收配置中声明待验证视觉候选，必须通过实际图片请求才算支持')
    parser.add_argument('--vision-observer-model',help='隔离验收的独立视觉观察模型，不获得工具权限')
    parser.add_argument('--executor-model',help='只对该执行模型运行工程用例；其他模型只作观察者')
    parser.add_argument('--exclude-model',action='append',default=[])
    parser.add_argument('--candidate-model',action='append',default=[],help='Exact model ID returned by the discovery report; isolated catalog only')
    parser.add_argument('--discovery-report',type=Path)
    parser.add_argument('--resume-report',type=Path,help='恢复本轮受控验收工程，不重新实现或重新创建原任务')
    parser.add_argument('--verify-completed',action='store_true',help='只核对已完成任务及其真实测试，不启动新模型请求')
    parser.add_argument('--resume-case',default='coupon')
    parser.add_argument('--prepared-fixture',type=Path,help='复用已完成依赖安装的受控 React/Electron 工程')
    parser.add_argument('--reuse-project',type=Path,help='真实 GUI 复用先前已由 Agent 修复的受控工程')
    parser.add_argument('--gui-only',action='store_true',help='专项核对仅界面操作不能被标为代码验证通过')
    parser.add_argument('--only-model',action='append',default=[],help='Run actual Agent cases only for these allowed IDs')
    parser.add_argument('--data-dir',type=Path,default=Path(os.environ.get('APPDATA',Path.home()))/'local-coding-agent-desktop')
    parser.add_argument('--output',type=Path,default=ROOT/'validation-reports/unified-live')
    parser.add_argument('--max-calls',type=int,default=180)
    parser.add_argument('--max-tokens',type=int,default=20000000)
    args=parser.parse_args()
    if args.prepared_fixture and (len(args.case)!=1 or args.case[0] not in {'react','electron'} or not args.prepared_fixture.resolve().is_relative_to(ROOT/'validation-reports')):
        parser.error('Prepared fixture must be a controlled frontend case')
    if args.reuse_project and (not args.case or 'gui' not in args.case or not args.reuse_project.resolve().is_relative_to(ROOT/'validation-reports')):parser.error('GUI reuse must remain inside controlled validation projects')
    if args.gui_only and args.case!=['gui']:parser.error('GUI-only requires exactly the GUI case')
    if args.resume_report:
        if not args.live:parser.error('Resume requires explicit --live')
        previous=json.loads(args.resume_report.read_text(encoding='utf-8'))
        original=json.loads((args.resume_report.parent/'manifest.json').read_text(encoding='utf-8'))
        case=next((c for c in previous['cases'] if c['name']==args.resume_case),None)
        if args.verify_completed and (not case or case.get('runtime',{}).get('phase')!='completed'):
            parser.error('只允许核对已经完成的真实任务')
        if not case or (not (case.get('runtime',{}).get('plan_id') or case.get('runtime',{}).get('recovery_plan_id')) and case.get('name') not in {'react','electron'}):parser.error('Original case has no recoverable plan')
        for value in (original['data'],case['folder']):
            if not Path(value).resolve().is_relative_to(ROOT/'validation-reports'):parser.error('Resume outside controlled validation directory')
        args.output.mkdir(parents=True,exist_ok=False)
        manifest={**original,'output':str(args.output.resolve()),'report':str((args.output/'report.json').resolve()),
                  'resume_case':case,'resume_source':str(args.resume_report.resolve()),'verify_completed':args.verify_completed,'max_calls':25,'max_tokens':500000}
        path=args.output/'manifest.json';path.write_text(json.dumps(manifest),encoding='utf-8')
        if args.headless_runtime:
            from agent.desktop.resources import require_resources,MIB
            threshold=128 if args.verify_completed else 512
            require_resources(minimum_available=threshold*MIB,minimum_commit=threshold*MIB)
            if args.verify_completed:
                command=['uv','run','--locked','python',str(ROOT/'scripts/validation/runtime_live.py'),str(path.resolve())]
            else:
                executable=subprocess.check_output(['node','-p',"require('./desktop/node_modules/electron')"],cwd=ROOT,text=True).strip()
                command=[executable,str(ROOT/'scripts/validation/runtime_live_bridge.cjs'),str(path.resolve())]
        else:command=['node',str(ROOT/'scripts/validation/unified_live.cjs'),str(path.resolve())]
        env={**os.environ,'PYTHONUTF8':'1'};env.pop('ELECTRON_RUN_AS_NODE',None)
        code=run_controller(command,env,timeout=1000,report_path=args.output/'report.json')
        code=controller_result(code,args.output/'report.json')
        print(json.dumps({'exit_code':code,'report':manifest['report']},ensure_ascii=False));return code
    policy=ROOT/'validation-reports/unified-model-policy.json'
    excluded=['qwen3.7-plus','qwen3.8-flash']+args.exclude_model+(json.loads(policy.read_text(encoding='utf-8')).get('excluded_models',[]) if policy.exists() else [])
    if any(not isinstance(model,str) or not 1<=len(model)<=200 for model in excluded):
        parser.error('Invalid excluded model ID')
    if not 1<=args.max_calls<=500 or not 1<=args.max_tokens<=30000000:
        parser.error('Live caps out of range')
    if not 1<=args.request_seconds<=180:
        parser.error('Request timeout must be between 1 and 180 seconds')
    if not 256<=args.output_tokens<=8192:parser.error('Output limit must be between 256 and 8192')
    if args.validation_task_calls is not None and not 1<=args.validation_task_calls<=100:parser.error('Invalid isolated task call cap')
    if args.validation_task_tokens is not None and not 1<=args.validation_task_tokens<=2000000:parser.error('Invalid isolated task token cap')
    catalog=load_catalog(args.data_dir)
    ali=[c for c in catalog['connections'] if c['enabled'] and c['provider_type']=='openai_compatible' and urlsplit(c['base_url']).hostname and any(urlsplit(c['base_url']).hostname.endswith(s) for s in ('aliyuncs.com','dashscope.cn','dashscope-intl.aliyuncs.com'))]
    profiles=[p for p in catalog['profiles'] if p['connection_id'] in {c['connection_id'] for c in ali} and not any(name.casefold() in p['model_id'].casefold() for name in excluded)]
    if args.candidate_model:
        if not args.discovery_report:
            parser.error('Candidate models require an actual discovery report')
        discovered=json.loads(args.discovery_report.read_text(encoding='utf-8')).get('discovery',[])
        for model in args.candidate_model:
            connection=next((c for c in ali if any(c['connection_id']==item['connection_id'] and model in item['models'] for item in discovered)),None)
            if not connection or any(name.casefold() in model.casefold() for name in excluded):
                parser.error('Candidate missing from verified discovery or excluded by user')
            if any(p['model_id']==model and p['connection_id']==connection['connection_id'] for p in profiles):continue
            profiles.append({'model_profile_id':'validation-'+hashlib.sha256((connection['connection_id']+model).encode()).hexdigest()[:24],
                             'connection_id':connection['connection_id'],'model_id':model,'display_name':model,
                             'context_window':65536,'max_output_tokens':8192,'temperature':0.1,'pricing':None,'tool_mode':'auto','supports_vision':False})
    if args.only_model:
        profiles=[p for p in profiles if p['model_id'] in args.only_model]
        if set(args.only_model)-{p['model_id'] for p in profiles}:parser.error('Requested model missing or excluded')
    if args.allowed_model:
        if set(args.candidate_model+args.only_model)-set(args.allowed_model):parser.error('本轮候选模型不在正向白名单中')
        profiles=[p for p in profiles if p['model_id'] in args.allowed_model]
    profiles=[{**p,'supports_vision':True} if p['model_id'] in args.vision_candidate_model else p for p in profiles]
    inventory=[{k:p.get(k) for k in ('model_profile_id','model_id','context_window','max_output_tokens','tool_mode')} for p in profiles]
    if not args.live:
        print(json.dumps({'result':'NOT RUN','inventory':inventory,'credentials_read':False},ensure_ascii=False));return
    args.output.mkdir(parents=True,exist_ok=False)
    from agent.desktop.resources import require_resources,MIB,memory_snapshot
    threshold=512 if args.headless_runtime else 1024
    try:require_resources(minimum_available=threshold*MIB,minimum_commit=threshold*MIB)
    except Exception as exc:
        (args.output/'report.json').write_text(json.dumps({'result':'BLOCKED_RESOURCE','error_code':getattr(exc,'code',type(exc).__name__),'memory':memory_snapshot(),'models':[],'cases':[]}),encoding='utf-8')
        print('BLOCKED_RESOURCE: 未启动 Electron 或模型请求。');return 1
    reopen=None
    if args.reopen_memory_report:
        source=args.reopen_memory_report.resolve()
        if not source.is_relative_to((ROOT/'validation-reports').resolve()):parser.error('Memory source must be an isolated validation report')
        previous=json.loads(source.read_text(encoding='utf-8'))
        reopen=next((c for c in previous.get('cases',[]) if c['name']=='project-memory' and c['result']=='PASS'),None)
        if not reopen:parser.error('No passed project memory case to reopen')
        original=json.loads((source.parent/'manifest.json').read_text(encoding='utf-8'))
        data=Path(original['data']).resolve()
        if not data.is_relative_to((ROOT/'validation-reports').resolve()) or not Path(reopen['folder']).resolve().is_relative_to(source.parent):parser.error('Memory data/workspace boundary rejected')
    else:
        data=args.output/'agent';data.mkdir()
    # Isolated profile output/context limits, original catalog and keys stay unchanged.
    profiles=[{**p,'max_output_tokens':min(args.output_tokens,p.get('max_output_tokens') or args.output_tokens),'context_window':p.get('context_window') or 65536} for p in profiles]
    # 只读当前 Settings；验收不扩大用户已有任务/全局预算，也不改原配置。
    with sqlite3.connect((args.data_dir/'local-coding-agent.sqlite3').resolve().as_uri()+'?mode=ro',uri=True) as connection:
        row=connection.execute('SELECT value FROM settings WHERE key=?',('orchestration.config',)).fetchone()
    saved=validate_config(json.loads(row[0]) if row else {})
    if args.vision_observer_model:
        observer=next((p for p in profiles if p['model_id']==args.vision_observer_model and p.get('supports_vision')),None)
        if not observer:parser.error('Observer must be an explicitly declared vision profile')
        saved={**saved,'vision_profile_id':observer['model_profile_id']}
    limits={**saved['budget']}
    if args.validation_task_calls is not None:limits['api_calls']=args.validation_task_calls
    if args.validation_task_tokens is not None:limits['api_tokens']=args.validation_task_tokens
    # 用户额外授权仅作用于本轮隔离验收目录，仍受 CLI 有限总上限约束。
    if args.validation_task_calls is not None:limits['global_api_calls']=args.max_calls
    if args.validation_task_tokens is not None:limits['global_api_tokens']=args.max_tokens
    limits.update(api_calls=min(limits['api_calls'],40,args.max_calls),api_tokens=min(limits['api_tokens'],5000000,args.max_tokens),
                  global_api_calls=min(limits['global_api_calls'],args.max_calls),global_api_tokens=min(limits['global_api_tokens'],args.max_tokens),
                  task_seconds=min(limits['task_seconds'],600),request_seconds=min(limits['request_seconds'],args.request_seconds))
    args.max_calls=limits['global_api_calls'];args.max_tokens=limits['global_api_tokens']
    config=validate_config({**saved,'budget':limits})
    if args.installed_executable:
        executable=args.installed_executable.resolve()
        if not executable.is_file() or executable.name!='LocalCodingAgent.exe' or not executable.is_relative_to(ROOT/'build'):
            parser.error('安装版必须在本仓库 build 隔离安装路径内')
    store=SQLiteStore(data)
    if args.full_access:
        from agent.permissions.authorization import AuthorizationSettings
        AuthorizationSettings(store).configure('full_access',confirmed=True)
    store.set_setting(KEY,json.dumps({'connections':ali,'profiles':profiles}))
    store.set_setting('orchestration.config',json.dumps(config))
    if args.reuse_capabilities:
        cached=json.loads(args.reuse_capabilities.read_text(encoding='utf-8'))
        for item in cached.get('models',[]):
            if item.get('capability') and any(p['model_profile_id']==item['profile_id'] and p['model_id']==item['model_id'] for p in profiles):
                store.set_setting('model.test.'+item['profile_id'],json.dumps(item['capability']))
    # Seed synthetic conversation history before the backend starts. No task
    # states, tool successes or business implementation are manufactured.
    context=args.output/'context-project';prepare(context)
    from agent.server.projects import ProjectRegistry
    project,thread,_=ProjectRegistry(store).open(str(context.resolve()),active_model='profile:'+profiles[0]['model_profile_id'])
    for i in range(80):
        project.state.append_message(thread.id,role='user',content=f'历史诊断数据 {i}，无待执行操作：'+('synthetic log data '*300))
        project.state.append_message(thread.id,role='assistant',content='仅为上下文压力测试的历史填充，不代表工具执行证据。'+('historical summary '*300))
    store.connection.close()
    manifest={'root':str(ROOT),'credential_data':str(args.data_dir.resolve()),'data':str(data.resolve()),
              'output':str(args.output.resolve()),'profiles':profiles,'connections':ali,'config':config,'suite':args.suite,
              'max_calls':args.max_calls,'max_tokens':args.max_tokens,'report':str((args.output/'report.json').resolve()),
              'context_project':str(context.resolve()),'reuse_capabilities':str(args.reuse_capabilities.resolve()) if args.reuse_capabilities else None,
              'source_commit':subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip()}
    manifest.update(excluded_models=excluded,allowed_models=args.allowed_model,discover_only=args.discover_only,case_names=args.case,request_seconds=args.request_seconds)
    manifest['installed_executable']=str(args.installed_executable.resolve()) if args.installed_executable else None
    manifest['full_access']=args.full_access
    manifest['capabilities_only']=args.capabilities_only
    manifest['executor_model']=args.executor_model
    if args.prepared_fixture:manifest['prepared_fixture']=str(args.prepared_fixture.resolve())
    if args.reuse_project:manifest['reuse_project']=str(args.reuse_project.resolve())
    manifest['gui_only']=args.gui_only
    manifest['automatic_routing']=args.automatic_routing
    manifest['isolate_git_path']=args.isolate_git_path
    manifest['git_fixture_directory']=str(Path(shutil.which('git')).parent) if shutil.which('git') else None
    if reopen:manifest['memory_project']=reopen['folder']
    path=args.output/'manifest.json';path.write_text(json.dumps(manifest),encoding='utf-8')
    (args.output/'report.json').write_text(json.dumps({'result':'RUNNING','inventory':inventory}),encoding='utf-8')
    env={**os.environ,'PYTHONUTF8':'1'}
    if args.headless_runtime:
        if not args.allowed_model or args.discover_only or args.capabilities_only or any(n not in {'workflow-python','workflow-react','repair','interruption','websocket','environment'} for n in args.case):parser.error('无窗口 Runtime 仅支持已知能力模型的白名单工程用例')
        executable=subprocess.check_output(['node','-p',"require('./desktop/node_modules/electron')"],cwd=ROOT,text=True).strip()
        env.pop('ELECTRON_RUN_AS_NODE',None)
        command=[executable,str(ROOT/'scripts/validation/runtime_live_bridge.cjs'),str(path.resolve())]
    else:command=['node',str(ROOT/'scripts/validation/unified_live.cjs'),str(path.resolve())]
    code=run_controller(command,env,timeout=3900,report_path=args.output/'report.json',startup_timeout=700 if args.headless_runtime else 360)
    code=controller_result(code,args.output/'report.json')
    print(json.dumps({'exit_code':code,'report':str(args.output/'report.json')},ensure_ascii=False))
    return code


if __name__=='__main__':
    raise SystemExit(main())
