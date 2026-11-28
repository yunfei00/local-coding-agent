import {useEffect,useRef,useState} from "react";
import {Modal} from "./Modal";
type Result={hits:{file:string;line?:number;text?:string}[];truncated:boolean;skipped:number};
export function ProjectSearchDialog({onClose}:{onClose:()=>void}){
 const [query,setQuery]=useState("");
 const [mode,setMode]=useState<"file"|"text">("text");
 const [result,setResult]=useState<Result>();
 const [error,setError]=useState("");
 const [busy,setBusy]=useState(false);
 const active=useRef(false);
 useEffect(()=>()=>{if(active.current)void window.localAgent.cancelProjectSearch?.().catch(()=>{});},[]);
 async function search(){
  if(active.current||!query.trim()||!window.localAgent.searchProject)return;
  active.current=true;setBusy(true);setError("");setResult(undefined);
  try{setResult(await window.localAgent.searchProject(query,mode));}
  catch(e){setError(String(e));}
  finally{active.current=false;setBusy(false);}
 }
 return <Modal title="工程搜索" busy={busy} onClose={onClose}>
  <form onSubmit={e=>{e.preventDefault();void search();}}>
   <label>搜索类型 <select value={mode} disabled={busy} onChange={e=>setMode(e.target.value==="file"?"file":"text")}><option value="text">代码内容</option><option value="file">文件路径</option></select></label>
   <input aria-label="搜索关键词" value={query} maxLength={512} disabled={busy} onChange={e=>setQuery(e.target.value)}/>
   <button type="submit" disabled={busy||!query.trim()}>搜索</button>
   <button type="button" disabled={!busy} onClick={()=>void window.localAgent.cancelProjectSearch?.().catch(e=>setError(String(e)))}>停止</button>
   {error&&<p role="alert">{error}</p>}
   {result&&<><p role="status">匹配 {result.hits.length} 条，跳过 {result.skipped} 项{result.truncated?"（结果受限）":""}</p><div style={{maxHeight:360,overflow:"auto"}}>{result.hits.map((hit,i)=><div key={i}><strong>{hit.file}{hit.line?":"+hit.line:""}</strong>{hit.text!==undefined&&<pre style={{whiteSpace:"pre-wrap"}}>{hit.text}</pre>}</div>)}</div></>}
   <button type="button" disabled={busy} onClick={onClose}>关闭</button>
  </form>
 </Modal>;
}
