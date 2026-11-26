import {useEffect,useRef,useState} from "react";
import {ToolExecutionCards,appendToolEvent,type ToolCard,type ToolEvent} from "./ToolExecutionCards";
import {Modal} from "./Modal";

export function OpenCodeChatDialog({onClose}:{onClose:()=>void}){
  const [saveHistory,setSaveHistory]=useState(false);
  const [history,setHistory]=useState<{id:string;model:string;createdAt:string;messages:string[];output:string;status:string;sessionId?:string}[]>([]);
  const [historyOpen,setHistoryOpen]=useState(false);
  async function loadHistory(){
    try{setHistory(await window.localAgent.listLocalChatHistory?.()??[]);setHistoryOpen(true);}
    catch(error){setStatus("历史读取失败："+String(error));}
  }
  const [model,setModel]=useState("gemma4:31b");
  const [port,setPort]=useState("11434");
  const [prompt,setPrompt]=useState("");
  const [followups,setFollowups]=useState<string[]>([]);
  const [cards,setCards]=useState<ToolCard[]>([]);
  const [progress,setProgress]=useState<string[]>([]);
  const [output,setOutput]=useState("");
  const [status,setStatus]=useState("未开始");
  const [busy,setBusy]=useState(false);
  const running=useRef(false);
  useEffect(()=>{
    const unsubscribe=window.localAgent.onLocalChatDelta?.(delta=>{
      if(running.current)setOutput(previous=>previous+delta);
    });
    const offProgress=window.localAgent.onLocalChatProgress?.(raw=>{
      if(!running.current)return;
      const event=raw as {kind?:string;payload?:{type?:string;outcome?:string}};
      if(event.kind==="tool"&&typeof event.payload?.type==="string"){
        setCards(previous=>appendToolEvent(previous,event.payload as ToolEvent));return;
      }
      const label=event.kind==="tool"?event.payload?.type:event.kind==="usage"?"用量已更新":event.kind==="execution-ended"?"执行终态："+event.payload?.outcome:undefined;
      if(label)setProgress(previous=>[...previous.slice(-49),label]);
    });
    return ()=>{offProgress?.();unsubscribe?.();if(running.current)void window.localAgent.cancelLocalChat?.().catch(()=>{});};
  },[]);
  async function run(){
    if(running.current||!window.localAgent.runLocalChat)return;
    const number=Number(port);
    if(!model.trim()||!prompt.trim()||!Number.isInteger(number)||number<1||number>65535){setStatus("请输入有效模型、端口和消息");return;}
    running.current=true;setBusy(true);setOutput("");setProgress([]);setCards([]);setStatus("正在启动，请选择固定版本 OpenCode EXE");
    try{
      const result=await window.localAgent.runLocalChat({model:model.trim(),port:number,prompt,messages:[prompt,...followups.filter(message=>message.trim())],saveHistory});
      setStatus(result.outcome==="succeeded"?"对话结束（未独立验证）":result.outcome==="cancelled"||result.outcome==="interrupted"?"已取消或中断":"执行失败："+result.outcome);
    }catch(error){setStatus("执行未确认："+String(error));}
    finally{running.current=false;setBusy(false);}
  }
  return <Modal title="OpenCode 本地对话实验" busy={busy} onClose={onClose}>
    <p className="modal-description">仅限本地 Ollama 纯文本最多二十轮预设消息对话，不允许文件或命令工具。每次启动独立会话。需显式启用实验功能。</p>
    <form onSubmit={event=>{event.preventDefault();void run();}}>
      <label>模型 <input value={model} disabled={busy} onChange={e=>setModel(e.target.value)}/></label>
      <label>Ollama 回环端口 <input type="number" min={1} max={65535} value={port} disabled={busy} onChange={e=>setPort(e.target.value)}/></label>
      <label>消息 <textarea rows={4} value={prompt} disabled={busy} onChange={e=>setPrompt(e.target.value)}/></label>
      {followups.map((message,i)=><label key={i}>第 {i+2} 轮消息 <textarea rows={2} value={message} disabled={busy} onChange={e=>setFollowups(previous=>previous.map((v,j)=>j===i?e.target.value:v))}/><button type="button" disabled={busy} onClick={()=>setFollowups(previous=>previous.filter((_,j)=>j!==i))}>删除</button></label>)}
      <button type="button" disabled={busy||followups.length>=19} onClick={()=>setFollowups(previous=>[...previous,""])}>添加下一轮消息</button>
      <label><input type="checkbox" checked={saveHistory} disabled={busy} onChange={e=>setSaveHistory(e.target.checked)}/> 保存本次对话到本机（明文）</label>
      <button type="button" disabled={busy||!window.localAgent.listLocalChatHistory} onClick={()=>void loadHistory()}>查看历史</button>
      {historyOpen&&<section aria-label="历史对话" style={{maxHeight:280,overflow:"auto"}}>{history.length===0?<p>暂无历史</p>:history.map(item=><details key={item.id}><summary>{item.createdAt} · {item.model} · {item.status}</summary><pre style={{whiteSpace:"pre-wrap"}}>{item.messages.join("\n\n")}</pre><pre style={{whiteSpace:"pre-wrap"}}>{item.output}</pre></details>)}<button type="button" onClick={()=>setHistoryOpen(false)}>收起历史</button></section>}
      <p role="status">{status}</p>
      <pre aria-label="OpenCode 输出" style={{whiteSpace:"pre-wrap",overflowWrap:"anywhere",maxHeight:240,overflow:"auto"}}>{output}</pre>
      {cards.length>0&&<ToolExecutionCards cards={cards}/>}
      {progress.length>0?<ul aria-label="执行事件">{progress.map((item,i)=><li key={i}>{item}</li>)}</ul>:null}
      <div className="modal-actions">
        <button type="button" disabled={!busy} onClick={()=>{setStatus("正在请求停止");void window.localAgent.cancelLocalChat?.().catch(error=>setStatus(String(error)));}}>停止</button>
        <button type="submit" disabled={busy||!prompt.trim()||!window.localAgent.runLocalChat}>发送</button>
        <button type="button" disabled={busy} onClick={onClose}>关闭</button>
      </div>
    </form>
  </Modal>;
}
