/* 验收驱动的进程证据边界，不替代产品审批或桌面动作。 */
const fs=require('node:fs');
const cp=require('node:child_process');
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
module.exports={readyProcessId,matchesReadyProcess,closeOwnedApplication};
