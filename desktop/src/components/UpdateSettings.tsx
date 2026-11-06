import {useEffect,useState} from 'react';
import type {UpdateState} from '../../electron/updateManager';

const labels:Record<UpdateState['state'],string>={IDLE:'尚未检查',CHECKING:'正在检查',UP_TO_DATE:'已是最新版本',AVAILABLE:'发现新版本',DOWNLOADING:'正在下载',VERIFYING:'正在校验 SHA256',READY_TO_INSTALL:'已下载并通过校验',ERROR:'更新失败',CANCELLED:'已取消下载'};
export function UpdateSettings(){
 const [status,setStatus]=useState<UpdateState|null>(null),[error,setError]=useState(''),[later,setLater]=useState(false);
 useEffect(()=>{if(!window.localAgent.getUpdateState)return;void window.localAgent.getUpdateState().then(setStatus).catch(e=>setError(String(e)));return window.localAgent.onUpdateState(setStatus);},[]);
 const act=async(fn:()=>Promise<unknown>)=>{setError('');setLater(false);try{await fn();}catch(e){setError(String(e));}finally{if(window.localAgent.getUpdateState)void window.localAgent.getUpdateState().then(setStatus).catch(()=>{});}};
 const busy=status&&['CHECKING','DOWNLOADING','VERIFYING'].includes(status.state);
 return <div className="settings-update-card" aria-label="软件更新">
  <strong>软件更新 · 手动安装</strong>
  <p>检查 GitHub Releases，下载并校验后，由你关闭软件并手动安装。不会自动退出、停止任务、安装或重启。</p>
  <p>当前版本：{status?.current_version||'读取中'} · 平台：{status?.platform||window.localAgent.platform}{status?.portable?' · Portable':''}</p>
  <p>更新源：{status?.source||'https://github.com/yunfei00/local-coding-agent/releases'}</p>
  {status?.version&&<p>最新版本：v{status.version}</p>}
  {status&&<p role="status">{labels[status.state]}</p>}
  {status?.state==='DOWNLOADING'&&<div>{status.total?<progress value={status.bytes} max={status.total}/>:<progress/>}<p>{status.bytes.toLocaleString()} 字节{status.total?` / ${status.total.toLocaleString()} 字节`:' · 总大小未知'}</p></div>}
  {status?.notes&&<details><summary>版本说明</summary><pre style={{whiteSpace:'pre-wrap'}}>{status.notes}</pre></details>}
  {status?.sha256&&<p style={{overflowWrap:'anywhere'}}>SHA256 已通过：{status.sha256}</p>}
  {status?.state==='READY_TO_INSTALL'&&!later&&<p>{status.message||'安装包已下载并通过校验，请关闭软件后手动安装新版本。'}</p>}
  {(error||status?.error)&&<p role="alert">{error||status?.error}</p>}
  <div className="settings-update-actions">
   <button className="settings-secondary" disabled={!!busy} onClick={()=>void act(()=>window.localAgent.checkForUpdates())}>检查更新</button>
   <button disabled={!!busy||!status||status.state==='UP_TO_DATE'||status.state==='IDLE'} onClick={()=>void act(()=>window.localAgent.downloadUpdate())}>{status?.state==='ERROR'||status?.state==='CANCELLED'?'重新下载':'下载更新'}</button>
   {status?.state==='DOWNLOADING'&&<button onClick={()=>void act(()=>window.localAgent.cancelUpdateDownload())}>取消下载</button>}
   <button disabled={status?.state!=='READY_TO_INSTALL'} onClick={()=>void act(()=>window.localAgent.openUpdatePackage())}>{status?.portable?'打开便携包':'打开安装包'}</button>
   <button disabled={status?.state!=='READY_TO_INSTALL'} onClick={()=>void act(()=>window.localAgent.openUpdateFolder())}>打开所在文件夹</button>
   <button disabled={status?.state!=='READY_TO_INSTALL'} onClick={()=>setLater(true)}>稍后安装</button>
  </div>
 </div>;
}
