import {useEffect,useRef,useState} from "react";
import {Modal} from "./Modal";
type Diff={status:string;unstaged:string;staged:string};
export function ProjectDiffDialog({onClose}:{onClose:()=>void}){
 const [data,setData]=useState<Diff>();
 const [tab,setTab]=useState<keyof Diff>("unstaged");
 const [busy,setBusy]=useState(false);
 const [error,setError]=useState("");
 const active=useRef(false);
 async function refresh(){
  if(active.current||!window.localAgent.readProjectDiff)return;
  active.current=true;setBusy(true);setError("");setData(undefined);
  try{setData(await window.localAgent.readProjectDiff());}
  catch(e){setError(String(e));}
  finally{active.current=false;setBusy(false);}
 }
 useEffect(()=>{void refresh();},[]);
 return <Modal title="工程 Git 差异" busy={busy} onClose={onClose}>
  <p>显示当前工作区差异（包含用户已有修改，并非仅本次 Agent 修改）。未跟踪文件仅显示状态。</p>
  <div className="modal-actions">
   {(["status","unstaged","staged"] as const).map(key=><button key={key} type="button" aria-pressed={tab===key} onClick={()=>setTab(key)}>{key==="status"?"文件状态":key==="staged"?"已暂存":"未暂存"}</button>)}
   <button type="button" disabled={busy} onClick={()=>void refresh()}>刷新</button>
  </div>
  {busy&&<p role="status">正在读取 Git 差异</p>}
  {error&&<p role="alert">{error}</p>}
  {data&&<pre style={{maxHeight:420,overflow:"auto",whiteSpace:"pre-wrap",overflowWrap:"anywhere"}}>{(data[tab]||"无差异").split("\n").map((line,i)=><span key={i} style={{display:"block",color:tab!=="status"&&line.startsWith("+")&&!line.startsWith("+++")?"#16803c":tab!=="status"&&line.startsWith("-")&&!line.startsWith("---")?"#c24141":undefined}}>{line||" "}</span>)}</pre>}
  <button type="button" disabled={busy} onClick={onClose}>关闭</button>
 </Modal>;
}
