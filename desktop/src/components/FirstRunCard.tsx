import {useEffect,useState} from 'react';

export function FirstRunCard({ready,onModels}:{ready:boolean;onModels:()=>void}){
  const [environment,setEnvironment]=useState<Record<string,unknown>|null>(null);
  const [error,setError]=useState('');
  useEffect(()=>{
    if(!ready||!window.localAgent.environment)return;
    let alive=true;
    void window.localAgent.environment().then(event=>{if(alive)setEnvironment(event.payload||{});}).catch(cause=>{if(alive)setError(String(cause));});
    return()=>{alive=false;};
  },[ready]);
  const tools=environment?.tools as Record<string,boolean>|undefined;
  const memory=environment?.memory as {supported?:boolean;available_bytes?:number}|undefined;
  return <section aria-label="首次启动与环境诊断" className="settings-update-card">
    <strong>开始使用：选择或创建工程 → 配置模型 → 输入需求</strong>
    <p>应用自带运行后端。Git、Python、Node 和 uv 是用户工程的可选工具，缺少它们不会阻止进入主界面。</p>
    <button type="button" onClick={onModels}>配置模型</button>
    <details><summary>环境诊断</summary>
      {!ready?<p>正在连接后端…</p>:error?<p role="alert">{error}</p>:environment?<>
        <p>后端：{environment.backend_ready?'已就绪':'未就绪'}；运行方式：{environment.bundled_backend?'内置后端':'开发环境'}</p>
        <p>系统：{String(environment.windows)}；磁盘可用：{Math.round(Number(environment.disk_free_bytes)/1024**3)} GiB</p>
        {memory?.supported&&<p>可用内存：{(Number(memory.available_bytes)/1024**3).toFixed(1)} GiB；大型任务串行执行。</p>}
        <p>已配置连接 {Number(environment.provider_connections)} 个，模型 {Number(environment.model_profiles)} 个。</p>
        <ul>{Object.entries(tools||{}).map(([name,present])=><li key={name}>{name}：{present?'可用':'未检测到（需要时再配置）'}</li>)}</ul>
        <p>网络：{String(environment.network)}</p>
      </>:<p>正在检查…</p>}
    </details>
  </section>;
}
