"""真实冻结 worker 的窗口发现、UIA 输入/点击及保存验证；不使用模型或用户工程。"""
import argparse
import json
import os
from pathlib import Path
import subprocess
import tempfile
import sys
import threading
import queue
import uuid


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('executable',type=Path)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    repo=Path(__file__).resolve().parents[2]
    compiler=Path(os.environ['WINDIR'])/'Microsoft.NET/Framework64/v4.0.30319/csc.exe'
    report={'result':'RUNNING','model':'NOT_USED','worker':'frozen executable','operations':[]}
    fixture=None;temporary=None
    try:
        sys.path.insert(0,str(repo))
        from agent.desktop.session import require_interactive_session
        from agent.desktop.resources import require_resources
        require_resources();require_interactive_session()
        temporary=tempfile.TemporaryDirectory(prefix='lca-packaged-uia-')
        directory=temporary.name
        folder=Path(directory);program=folder/'GuiFixture.exe'
        built=subprocess.run([str(compiler),'/nologo','/target:exe','/out:'+str(program),'/reference:System.Windows.Forms.dll','/reference:System.Drawing.dll',str(repo/'manual-fixtures/v10-release-app/Main.cs')],capture_output=True,timeout=30)
        if built.returncode:raise RuntimeError('Native acceptance fixture compilation failed')
        fixture=subprocess.Popen([str(program),str(folder)],stdout=subprocess.PIPE,stderr=subprocess.PIPE,creationflags=subprocess.CREATE_NO_WINDOW)
        ready_lines=queue.Queue()
        threading.Thread(target=lambda:ready_lines.put(fixture.stdout.readline()),daemon=True).start()
        try:ready=ready_lines.get(timeout=30).decode('utf-8',errors='replace').strip()
        except queue.Empty:raise RuntimeError('Native fixture readiness exceeded 30 seconds')
        if ready!='LCA_GUI_READY pid='+str(fixture.pid):raise RuntimeError('Native fixture readiness not proven')
        def call(operation,arguments,binding=None):
            request={'operation':operation,'arguments':arguments}
            if binding:request['binding']=binding
            result=subprocess.run([str(args.executable.resolve()),'--desktop-worker'],input=json.dumps(request,ensure_ascii=False).encode('utf-8'),capture_output=True,timeout=45,creationflags=subprocess.CREATE_NO_WINDOW)
            if result.returncode:raise RuntimeError('Frozen worker exit='+str(result.returncode))
            response=json.loads(result.stdout)
            report['operations'].append({'operation':operation,'ok':response.get('ok'),'code':response.get('code')})
            if not response.get('ok'):raise RuntimeError(str(response.get('code'))+': '+str(response.get('message')))
            return response['data']
        windows=call('desktop_list_windows',{'pid':fixture.pid})['windows']
        if len(windows)!=1:raise RuntimeError('Frozen worker did not identify exactly one owned native window')
        binding=windows[0]['identity'];value='PACKAGED-'+uuid.uuid4().hex[:10]
        call('desktop_focus_window',{},binding)
        call('desktop_type_text',{'selector':{'automation_id':'DisplayName'},'text':value,'confirm_risk':True},binding)
        call('desktop_click',{'selector':{'automation_id':'Save'},'confirm_risk':True},binding)
        inspected=call('desktop_inspect',{},binding)
        if (folder/'gui-saved.txt').read_text(encoding='utf-8')!=value:raise RuntimeError('Native Save did not persist actual input')
        if not any(c.get('name')=='已保存：'+value for c in inspected['controls']):raise RuntimeError('Saved UIA status did not reflect the actual saved value')
        fixture.terminate();fixture.wait(timeout=10);fixture=None
        report.update(result='PASS',owned_window=True,saved_file=True,saved_uia_status=True,fixture_exited=True)
    except Exception as exc:
        code=getattr(exc,'code','')
        blocked=code in {'DESKTOP_SESSION_LOCKED','DESKTOP_SESSION_UNAVAILABLE','DESKTOP_SECURE_DESKTOP','BLOCKED_RESOURCE'}
        report.update(result='BLOCKED' if blocked else 'FAIL',error_code=code,error=str(exc)[:700])
    finally:
        if fixture:
            fixture.terminate();fixture.wait(timeout=10)
        if temporary:temporary.cleanup()
        args.output.parent.mkdir(parents=True,exist_ok=True)
        args.output.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False))
    return 0 if report['result']=='PASS' else 1


if __name__=='__main__':raise SystemExit(main())
