/* 验收驱动的进程证据边界，不替代产品审批或桌面动作。 */
const fs=require('node:fs');
const cp=require('node:child_process');
const path=require('node:path');
function nativeProcessReleaseEvidence(operations,folder,lookup){
 const pid=operations?.find(item=>item.name==='desktop_list_windows'&&Number.isInteger(item.pid)&&item.pid>0)?.pid;
 if(!pid)return {released:false,reason:'NO_ORIGINAL_PID'};
 try{
  const process=lookup(pid);
  if(process===null)return {released:true,pid,reason:'ORIGINAL_PID_EXITED'};
  if(typeof process?.path!=='string'||!process.path)return {released:false,pid,reason:'IDENTITY_UNAVAILABLE'};
  const expected=path.resolve(folder,'GuiFixture.exe').toLowerCase();
  return {released:path.resolve(process.path).toLowerCase()!==expected,pid,reason:path.resolve(process.path).toLowerCase()===expected?'ORIGINAL_FIXTURE_STILL_RUNNING':'PID_REUSED_BY_DIFFERENT_IMAGE'};
 }catch{return {released:false,pid,reason:'PROCESS_CHECK_FAILED'};}
}
function readyProcessId(stdout){
 const match=/M5_ELECTRON_READY (\{[^\r\n]+\})/.exec(stdout||'');
 try{const pid=JSON.parse(match?.[1]||'null')?.pid;return Number.isInteger(pid)&&pid>0?pid:null;}catch{return null;}
}
function matchesReadyProcess(requested,ready,file){
 if(!Number.isInteger(requested)||requested<=0||requested!==ready)return false;
 try{return JSON.parse(fs.readFileSync(file,'utf8')).pid===ready;}catch{return false;}
}
async function closeOwnedApplication(app,child,{timeout=10000,kill=pid=>{if(process.platform==='win32')cp.spawnSync('taskkill',['/PID',String(pid),'/T','/F'],{windowsHide:true,stdio:'ignore'});else child.kill('SIGKILL');}}={}){
 let timer,forced=false;
 try{await Promise.race([app.close().catch(()=>{}),new Promise(resolve=>{timer=setTimeout(resolve,timeout);})]);}finally{clearTimeout(timer);}
 if(child?.exitCode===null&&child.pid){forced=true;kill(child.pid);await new Promise(resolve=>setTimeout(resolve,50));}
 return {exit_code:child?.exitCode??null,signal:child?.signalCode??null,forced};
}
function visualWaitEvidence(args={}){
 // Only the controlled fixture's public labels may enter a report.
 const label=value=>value===undefined?null:['Visual fallback verified','Waiting for real pointer input'].includes(value)?value:'[redacted]';
 const selector=args.selector;
 const state=args.state??'exists',seconds=args.seconds??5;
 return {state:['exists','enabled','disabled','visible','hidden','name'].includes(state)?state:'[invalid]',seconds:typeof seconds==='number'&&Number.isFinite(seconds)&&seconds>=0&&seconds<=30?seconds:null,selector_present:selector!=null,
  selector_keys:selector&&typeof selector==='object'?Object.keys(selector).filter(k=>['name','automation_id','control_type','runtime_id'].includes(k)):[],
  selector_name:label(selector?.name),expected:label(args.expected)};
}
module.exports={readyProcessId,matchesReadyProcess,closeOwnedApplication,visualWaitEvidence,nativeProcessReleaseEvidence};
