import {useEffect,useRef,useState} from "react";
import {Modal} from "./Modal";

export function OpenCodeChatDialog({onClose}:{onClose:()=>void}){
  const [model,setModel]=useState("gemma4:31b");
  const [port,setPort]=useState("11434");
  const [prompt,setPrompt]=useState("");
  const [output,setOutput]=useState("");
  const [status,setStatus]=useState("未开始");
  const [busy,setBusy]=useState(false);
  const running=useRef(false);
  useEffect(()=>{
    const unsubscribe=window.localAgent.onLocalChatDelta?.(delta=>{
      if(running.current)setOutput(previous=>previous+delta);
    });
    return ()=>{unsubscribe?.();if(running.current)void window.localAgent.cancelLocalChat?.().catch(()=>{});};
  },[]);
  async function run(){
    if(running.current||!window.localAgent.runLocalChat)return;
    const number=Number(port);
    if(!model.trim()||!prompt.trim()||!Number.isInteger(number)||number<1||number>65535){setStatus("请输入有效模型、端口和消息");return;}
    running.current=true;setBusy(true);setOutput("");setStatus("正在启动，请选择固定版本 OpenCode EXE");
    try{
      const result=await window.localAgent.runLocalChat({model:model.trim(),port:number,prompt});
      setStatus(result.outcome==="succeeded"?"对话结束（未独立验证）":result.outcome==="cancelled"||result.outcome==="interrupted"?"已取消或中断":"执行失败："+result.outcome);
    }catch(error){setStatus("执行未确认："+String(error));}
    finally{running.current=false;setBusy(false);}
  }
  return <Modal title="OpenCode 本地对话实验" busy={busy} onClose={onClose}>
    <p className="modal-description">仅限本地 Ollama 纯文本单轮对话，不允许文件或命令工具。每次启动独立会话。需显式启用实验功能。</p>
    <form onSubmit={event=>{event.preventDefault();void run();}}>
      <label>模型 <input value={model} disabled={busy} onChange={e=>setModel(e.target.value)}/></label>
      <label>Ollama 回环端口 <input type="number" min={1} max={65535} value={port} disabled={busy} onChange={e=>setPort(e.target.value)}/></label>
      <label>消息 <textarea rows={4} value={prompt} disabled={busy} onChange={e=>setPrompt(e.target.value)}/></label>
      <p role="status">{status}</p>
      <pre aria-label="OpenCode 输出" style={{whiteSpace:"pre-wrap",overflowWrap:"anywhere",maxHeight:240,overflow:"auto"}}>{output}</pre>
      <div className="modal-actions">
        <button type="button" disabled={!busy} onClick={()=>{setStatus("正在请求停止");void window.localAgent.cancelLocalChat?.().catch(error=>setStatus(String(error)));}}>停止</button>
        <button type="submit" disabled={busy||!prompt.trim()||!window.localAgent.runLocalChat}>发送</button>
        <button type="button" disabled={busy} onClick={onClose}>关闭</button>
      </div>
    </form>
  </Modal>;
}
