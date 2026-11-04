"""Explicit bounded live acceptance through the production Electron IPC; never decrypts keys."""
import argparse
import hashlib
import json
import os
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
    parser.add_argument('--suite',action='store_true')
    parser.add_argument('--reuse-capabilities',type=Path,help='Reuse this session capability evidence; actual Agent cases still run')
    parser.add_argument('--discover-only',action='store_true',help='List provider model IDs over the existing connection; no generation')
    parser.add_argument('--exclude-model',action='append',default=[])
    parser.add_argument('--candidate-model',action='append',default=[],help='Exact model ID returned by the discovery report; isolated catalog only')
    parser.add_argument('--discovery-report',type=Path)
    parser.add_argument('--only-model',action='append',default=[],help='Run actual Agent cases only for these allowed IDs')
    parser.add_argument('--data-dir',type=Path,default=Path(os.environ.get('APPDATA',Path.home()))/'local-coding-agent-desktop')
    parser.add_argument('--output',type=Path,default=ROOT/'validation-reports/unified-live')
    parser.add_argument('--max-calls',type=int,default=180)
    parser.add_argument('--max-tokens',type=int,default=20000000)
    args=parser.parse_args()
    policy=ROOT/'validation-reports/unified-model-policy.json'
    excluded=args.exclude_model+(json.loads(policy.read_text(encoding='utf-8')).get('excluded_models',[]) if policy.exists() else [])
    if any(not isinstance(model,str) or not 1<=len(model)<=200 for model in excluded):
        parser.error('Invalid excluded model ID')
    if not 1<=args.max_calls<=500 or not 1<=args.max_tokens<=30000000:
        parser.error('Live caps out of range')
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
    inventory=[{k:p.get(k) for k in ('model_profile_id','model_id','context_window','max_output_tokens','tool_mode')} for p in profiles]
    if not args.live:
        print(json.dumps({'result':'NOT RUN','inventory':inventory,'credentials_read':False},ensure_ascii=False));return
    args.output.mkdir(parents=True,exist_ok=False)
    data=args.output/'agent';data.mkdir()
    # Isolated profile output/context limits, original catalog and keys stay unchanged.
    profiles=[{**p,'max_output_tokens':8192,'context_window':p.get('context_window') or 65536} for p in profiles]
    config=validate_config({'budget':{'api_calls':40,'api_tokens':5000000,'global_api_calls':args.max_calls,'global_api_tokens':args.max_tokens,'task_seconds':600,'request_seconds':60,'local_repairs':3}})
    store=SQLiteStore(data)
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
    manifest.update(excluded_models=excluded,discover_only=args.discover_only)
    path=args.output/'manifest.json';path.write_text(json.dumps(manifest),encoding='utf-8')
    (args.output/'report.json').write_text(json.dumps({'result':'RUNNING','inventory':inventory}),encoding='utf-8')
    env={**os.environ,'PYTHONUTF8':'1'}
    code=run_controller(['node',str(ROOT/'scripts/validation/unified_live.cjs'),str(path.resolve())],env,timeout=3900,report_path=args.output/'report.json')
    print(json.dumps({'exit_code':code,'report':str(args.output/'report.json')},ensure_ascii=False))
    return code


if __name__=='__main__':
    raise SystemExit(main())
