"""v0.7 串行系统应用验收；仅作用于本次新建窗口。"""
import argparse,asyncio,json,os,sys,time,uuid
import re
import subprocess
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
from agent.desktop.resources import require_resources,MIB
from agent.tools.workspace import Workspace
from agent.tools.registry import ToolRegistry

async def run(args):
    output=args.output.resolve();output.mkdir(parents=True,exist_ok=False)
    os.environ['LCA_DATA_DIR']=str(output/'agent')
    report={'scenario':args.scenario,'result':'RUNNING','model':'无（真实生产工具集成）','events':[]}
    def save(): (output/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    registry=None;window=None;owner='v07-'+uuid.uuid4().hex;before=set()
    previous_owned=set()
    previous_pids=set();known_notes={}
    if args.scenario=='notepad':
        for path in (ROOT/'validation-reports').glob('v07-notepad*/report.json'):
            try:
                old=json.loads(path.read_text(encoding='utf-8'));w=old.get('window',{})
                if w.get('title','').startswith('v07-note-'):previous_owned.add((w['pid'],w['title']));previous_pids.add(w['pid'])
            except (OSError,ValueError,KeyError):pass
        known_notes={p.name:p for p in (ROOT/'validation-reports').glob('v07-notepad*/v07-note-*.txt')}
    async def call(name,**kw):
        if name.startswith('desktop_') and name!='desktop_list_windows':kw.setdefault('window_id',window);kw.setdefault('timeout_seconds',60)
        result=await registry.execute(name,kw,owner_id=owner,desktop_authorized=True)
        report['events'].append({'tool':name,'ok':result.ok,'data':result.data,'error':getattr(result,'error',None)});save()
        if not result.ok:raise RuntimeError(name+' failed')
        return result.data
    try:
        report['memory_before']=require_resources(minimum_available=1024*MIB,minimum_commit=1024*MIB)
        if getattr(args, 'gemma_notepad_fixture', False):
            processes = subprocess.check_output(
                ['tasklist', '/FI', 'IMAGENAME eq Notepad.exe', '/FO', 'CSV', '/NH'],
                text=True, errors='replace')
            if re.search(r'^"notepad\.exe"', processes, re.I | re.M):
                from agent.tools.base import ToolError
                raise ToolError('BLOCKED_RESOURCE', '已有记事本进程，无法确认独立窗口。')
        registry=ToolRegistry(Workspace(output));save()
        listed=await call('desktop_list_windows');before={w['window_id'] for w in listed['windows']}
        reusable={w['window_id'] for w in listed['windows'] if w['pid'] in previous_pids and any(w['title'].startswith(name+' - ') for name in known_notes)}
        marker='desktop-test' if getattr(args, 'gemma_notepad_fixture', False) else 'v07-note-'+uuid.uuid4().hex[:8]
        note=output/(marker+'.txt');note.write_text('',encoding='utf-8')
        browser_title='v07-browser-'+uuid.uuid4().hex[:8]
        if args.scenario=='browser':
            page=output/'local.html';page.write_text('<!doctype html><title>'+browser_title+'</title><style>body{font:24px system-ui;padding:32px}button{font-size:24px;padding:16px}</style><h1>Local browser page</h1><button onclick="document.querySelector(\'p\').textContent=\'Local page verified\'">Verify local page</button><p role="status">Waiting</p>',encoding='utf-8')
            edge=Path(os.environ.get('PROGRAMFILES(X86)','C:/Program Files (x86)'))/'Microsoft/Edge/Application/msedge.exe'
            if not edge.exists():raise RuntimeError('EDGE_NOT_INSTALLED')
        # UWP/Explorer 激活器会立即退出；保持本次受管理的 launcher，
        # 避免 Job 在真实窗口出现前清理其后代。始终有 120 秒上限。
        commands={'notepad':f'notepad.exe "{note}"','calculator':'Start-Process calc.exe; Start-Sleep -Seconds 120','explorer':f'Start-Process explorer.exe -ArgumentList \'/separate,"{output}"\'; Start-Sleep -Seconds 120'}
        if args.scenario=='browser':commands['browser']=f'& "{edge}" --user-data-dir="{output / "browser-profile"}" --no-first-run --no-default-browser-check --disable-extensions --disable-gpu --force-renderer-accessibility --app="{page.as_uri()}"; Start-Sleep -Seconds 120'
        process=await registry.processes.launch({'command':commands[args.scenario],'timeout_seconds':180},owner=owner)
        report['process_id']=process.id
        deadline=time.monotonic()+45
        while time.monotonic()<deadline:
            listed=await call('desktop_list_windows')
            new=[w for w in listed['windows'] if (w['window_id'] not in before or w['window_id'] in reusable) and (marker in w['title'] if args.scenario=='notepad' else ('计算器' in w['title'] or 'Calculator' in w['title']) if args.scenario=='calculator' else browser_title in w['title'] if args.scenario=='browser' else output.name in w['title'])]
            if len(new)==1:window=new[0]['window_id'];report['window']=new[0];break
            await asyncio.sleep(.5)
        if not window:raise RuntimeError('NO_UNIQUE_NEW_OWNED_WINDOW')
        await call('desktop_focus_window');tree=await call('desktop_inspect')
        report['controls']=tree['controls']
        if args.probe_only:report['result']='PROBED'
        elif args.scenario=='notepad':
            editors=[c for c in tree['controls'] if c['control_type'] in ('Edit','Document') and not c['sensitive']]
            if len(editors)!=1:raise RuntimeError('NO_UNIQUE_DOCUMENT')
            text='Local Coding Agent Gemma 桌面自动化测试成功' if getattr(args, 'gemma_notepad_fixture', False) else 'V07 中文记事本 '+marker
            await call('desktop_type_text',selector={'runtime_id':editors[0]['runtime_id']},text=text,confirm_risk=True)
            await call('desktop_keypress',keys='CTRL+S',confirm_risk=True)
            for _ in range(30):
                if note.read_text(encoding='utf-8-sig')==text:break
                await asyncio.sleep(.1)
            if note.read_text(encoding='utf-8-sig')!=text:raise RuntimeError('SAVED_FILE_MISMATCH')
            report.update(result='PASS',file_readback_verified=True,characters=len(text))
        elif args.scenario=='calculator':
            for name in ('clearButton','num2Button','plusButton','num3Button','equalButton'):
                await call('desktop_click',selector={'automation_id':name},confirm_risk=True)
            final=await call('desktop_inspect');result=[c for c in final['controls'] if c['automation_id']=='CalculatorResults']
            if len(result)!=1 or not result[0]['name'].rstrip().endswith('5'):raise RuntimeError('CALCULATOR_RESULT_MISMATCH')
            report.update(result='PASS',calculation='2+3=5',readback_verified=True)
        elif args.scenario=='explorer':
            target=output/'v07-owned-folder';target.mkdir()
            await call('desktop_keypress',keys='CTRL+L',confirm_risk=True)
            current=await call('desktop_inspect')
            boxes=[c for c in current['controls'] if c['control_type']=='Edit' and c['automation_id']=='TextBox' and c['visible'] and not c['sensitive']]
            if not boxes:raise RuntimeError('ADDRESS_EDITOR_UNAVAILABLE')
            address=max(boxes,key=lambda c:c['bounds'][2]-c['bounds'][0])
            await call('desktop_type_text',selector={'runtime_id':address['runtime_id']},text=str(target))
            await call('desktop_keypress',keys='ENTER',confirm_risk=True)
            verified=False
            for _ in range(10):
                windows=await call('desktop_list_windows')
                if any(w['window_id']==window and target.name in w['title'] for w in windows['windows']):verified=True;break
                await asyncio.sleep(.2)
            if not verified:raise RuntimeError('EXPLORER_NAVIGATION_NOT_VERIFIED')
            await call('desktop_keypress',keys='ALT+UP',confirm_risk=True)
            report.update(result='PASS',navigation_verified=True)
        elif args.scenario=='browser':
            await call('desktop_click',selector={'name':'Verify local page','control_type':'Button'},confirm_risk=True)
            await call('desktop_wait',selector={'name':'Local page verified'},state='exists',seconds=5)
            report.update(result='PASS',local_page_verified=True)
        save()
    except Exception as e:
        report.update(result='BLOCKED' if getattr(e,'code','')=='BLOCKED_RESOURCE' else 'FAIL',error_code=getattr(e,'code',type(e).__name__),reason=str(e)[:500])
    finally:
        if registry:
            if window:
                try:
                    current=await call('desktop_inspect')
                    top=report['window']['bounds'][1]
                    captions=[c for c in current['controls'] if c['control_type']=='Button' and c['name'] in ('关闭','Close') and c['bounds'][1]<top+80]
                    if len(captions)==1:await call('desktop_click',selector={'runtime_id':captions[0]['runtime_id']},confirm_risk=True)
                    else:await call('desktop_keypress',keys='ALT+F4',confirm_risk=True)
                except Exception as e:
                    report['close_error']=getattr(e,'code',type(e).__name__)
                    try:await call('desktop_keypress',keys='ALT+F4',confirm_risk=True)
                    except Exception as close:report['close_error']=getattr(close,'code',type(close).__name__)
            await registry.processes.close()
            if window:
                for _ in range(6):
                    remaining=await call('desktop_list_windows')
                    if not any(w['window_id']==window for w in remaining['windows']):report['window_closed']=True;break
                    await asyncio.sleep(.2)
                if not report.get('window_closed'):report.update(result='FAIL',close_error='OWNED_WINDOW_NOT_CLOSED')
            await registry.desktop.close_owner(owner)
            report['cleanup']={'active_workers':len(registry.desktop.workers),'running_managed_processes':sum(s.process.returncode is None for s in registry.processes.sessions.values())}
        save()
    print(json.dumps({'result':report['result'],'report':str(output/'report.json'),'error':report.get('error_code')}))
    return 0 if report['result'] in ('PASS','PROBED') else 1

def main():
    p=argparse.ArgumentParser();p.add_argument('--scenario',choices=['notepad','calculator','explorer','browser'],required=True);p.add_argument('--output',type=Path,required=True);p.add_argument('--probe-only',action='store_true')
    p.add_argument('--gemma-notepad-fixture', action='store_true')
    a=p.parse_args()
    if a.gemma_notepad_fixture and a.scenario != 'notepad':
        p.error('--gemma-notepad-fixture requires --scenario notepad')
    return asyncio.run(run(a))
if __name__=='__main__':raise SystemExit(main())
