import {useState} from 'react';
type Memory={id:string;title:string;content:string;category:string;trust:string;revision:number;updated:number;stale:boolean;sources:Record<string,string>};
type Hit={path:string;start_line:number;end_line:number;snippet:string;reason:string[];index_version:number};
const trust:Record<string,string>={candidate:'待验证候选',user:'用户确认',verified:'已验证事实'};
export function ProjectKnowledgePanel({threadId,running}:{threadId:string;running:boolean}){
 const [memories,setMemories]=useState<Memory[]>([]),[automatic,setAutomatic]=useState(true),[busy,setBusy]=useState(false),[error,setError]=useState('');
 const [query,setQuery]=useState(''),[title,setTitle]=useState(''),[content,setContent]=useState(''),[editing,setEditing]=useState<Memory>();
 const [hits,setHits]=useState<Hit[]>([]),[version,setVersion]=useState<number>();
 const request=async(operation:string,payload:Record<string,unknown>={})=>{
  setBusy(true);setError('');
  try{const event=await window.localAgent.taskRequest(threadId,operation,payload);const data=event.payload as {memories?:Memory[];automatic?:boolean;results?:Hit[];index?:{version:number}};
   if(data.memories)setMemories(data.memories);if(typeof data.automatic==='boolean')setAutomatic(data.automatic);if(data.results)setHits(data.results);if(data.index)setVersion(data.index.version);return true;
  }catch(cause){setError(String(cause));return false;}finally{setBusy(false);}
 };
 return <section className="context-section" aria-label="项目知识">
  <details onToggle={e=>{if(e.target===e.currentTarget && e.currentTarget.open)void request('knowledge.get');}}>
   <summary>项目长期记忆与工程检索</summary>
   <p>仅当前项目。候选不是事实；过期记忆以当前文件为准。不会保存凭据或全部聊天。</p>
   {error?<p className="error-banner">{error}</p>:null}
   <label><input type="checkbox" checked={automatic} disabled={busy||running} onChange={e=>void request('knowledge.settings',{enabled:e.target.checked})}/>自动提取项目事实与已验证解决方案</label>
   <input aria-label="记忆搜索" placeholder="搜索项目记忆" value={query} onChange={e=>setQuery(e.target.value)}/>
   <button type="button" disabled={busy} onClick={()=>void request('knowledge.get',{query})}>搜索记忆</button>
   <button type="button" disabled={busy||!query.trim()} onClick={()=>void request('knowledge.search',{query})}>检索工程</button>
   {version!==undefined?<p>内容索引版本 {version} · {hits.length} 项真实文件证据</p>:null}
   {hits.map((h,i)=><details key={h.path+':'+i}><summary>{h.path}:{h.start_line}–{h.end_line}</summary><p>{h.reason.join('、')} · 版本 {h.index_version}</p><pre style={{whiteSpace:'pre-wrap',overflowWrap:'anywhere'}}>{h.snippet}</pre></details>)}
   <ul>{memories.map(m=><li key={m.id}><strong>{m.title}</strong> · {trust[m.trust]||m.trust}{m.stale?' · 来源已变更/不可用':''}<p>{m.content}</p>
    <details><summary>来源与更新时间</summary><p>{new Date(m.updated*1000).toLocaleString('zh-CN')} · 修订 {m.revision}</p><pre>{JSON.stringify(m.sources,null,2)}</pre></details>
    <button type="button" disabled={busy||running} onClick={()=>{setEditing(m);setTitle(m.title);setContent(m.content);}}>编辑</button>
    <button type="button" disabled={busy||running} onClick={()=>void request('knowledge.delete',{id:m.id})}>删除</button>
   </li>)}</ul>
   <label>记忆标题<input aria-label="记忆标题" value={title} disabled={!!editing||running} onChange={e=>setTitle(e.target.value)} maxLength={160}/></label>
   <label>记忆内容<textarea aria-label="记忆内容" rows={3} value={content} disabled={running} onChange={e=>setContent(e.target.value)} maxLength={6000}/></label>
   <button type="button" disabled={busy||running||!title.trim()||!content.trim()} onClick={()=>void request('knowledge.save',{title,content,category:editing?.category||'decision',...(editing?{revision:editing.revision}:{})}).then(ok=>{if(ok){setTitle('');setContent('');setEditing(undefined);}})}>保存并确认</button>
   {editing?<button type="button" onClick={()=>{setEditing(undefined);setTitle('');setContent('');}}>取消编辑</button>:null}
   {busy?<p>正在读取当前项目知识…</p>:null}
  </details>
 </section>;
}
