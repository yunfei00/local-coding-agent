import {useEffect,useState} from "react";
type Task={id:string;engine:"opencode";model:string;status:string;startedAt:string;endedAt?:string;events:number;verified:false};
export function OpenCodeTaskList(){
 const [tasks,setTasks]=useState<Task[]>([]);
 const [error,setError]=useState("");
 const [stopping,setStopping]=useState(false);
 useEffect(()=>{
  let alive=true,busy=false;
  async function refresh(){
   if(busy||!window.localAgent.listOpenCodeTasks)return;
   busy=true;
   try{const rows=await window.localAgent.listOpenCodeTasks();if(alive){setTasks(rows);setError("");}}
   catch(e){if(alive)setError(String(e));}
   finally{busy=false;}
  }
  void refresh();const timer=setInterval(()=>void refresh(),1500);
  return ()=>{alive=false;clearInterval(timer);};
 },[]);
 if(!window.localAgent.listOpenCodeTasks)return null;
 return <section className="context-section" aria-label="OpenCode 实验任务"><h3>OpenCode 实验任务（全局）</h3><p>仅显示本次软件运行期间的实验任务，不属于当前工程的正式任务。</p>
 {error&&<p role="alert">{error}</p>}
 {tasks.length===0&&<p>暂无实验任务</p>}
 {tasks.map(task=><details key={task.id} open={task.status==="running"}><summary>{task.model} · {({running:"执行中",succeeded:"执行结束（未验收）",failed:"失败",interrupted:"中断",unknown:"状态未知"} as Record<string,string>)[task.status]??task.status}</summary><p>任务 ID：{task.id}</p><p>开始：{task.startedAt} · 结束：{task.endedAt??"—"}</p><p>执行事件：{task.events} · 独立验收：未执行</p>{task.status==="running"&&<button disabled={stopping||!window.localAgent.cancelLocalChat} onClick={async()=>{setStopping(true);try{await window.localAgent.cancelLocalChat?.(task.id);}catch(e){setError(String(e));}finally{setStopping(false);}}}>请求停止</button>}</details>)}
 </section>;
}
