import {useState} from 'react';
type Capability={state:string;source:string};
type Model={model_profile_id:string;connection_id:string;model_id:string;display_name:string;availability:string;context_window?:number;max_output_tokens?:number;prohibited:boolean;capabilities:Record<string,Capability>;last_failure?:{code:string}};
const labels:Record<string,string>={SUPPORTED:'支持',UNSUPPORTED:'不支持',UNKNOWN:'未知',AVAILABLE:'可用',UNAVAILABLE:'不可用'};
export function ModelCapabilitySummary(){
 const [models,setModels]=useState<Model[]>([]),[error,setError]=useState('');
 return <details onToggle={e=>{if(e.target===e.currentTarget&&e.currentTarget.open)void window.localAgent.taskRequest('','model.capabilities').then(r=>setModels((r.payload?.models||[]) as Model[])).catch(x=>setError(String(x)));}}>
  <summary>能力证据与自动路由状态</summary><p>只读取当前配置和缓存证据，不会启动时探测所有模型。未知能力不会当作支持；已禁止模型不会发送请求。</p>
  {error?<p className="error-banner">{error}</p>:null}
  {models.map(m=><details key={m.model_profile_id}><summary>{m.display_name} · {m.connection_id} / {m.model_id} · {m.prohibited?'已禁止':labels[m.availability]||m.availability}</summary>
   <p>配置上下文 {m.context_window||'未知'} · 输出上限 {m.max_output_tokens||'未知'}</p>
   <ul>{Object.entries({chat:'对话',streaming:'流式响应',tools:'工具调用',vision:'视觉理解',structured:'结构化输出'}).map(([key,label])=><li key={key}>{label}：{labels[m.capabilities[key]?.state]||'未知'} · {m.capabilities[key]?.source||'无证据'}</li>)}</ul>
   {m.last_failure?<p>最近错误：{m.last_failure.code}</p>:null}
  </details>)}
 </details>;
}
