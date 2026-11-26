import {useEffect,useRef,useState} from "react";
import {ToolExecutionCards,appendToolEvent,type ToolCard,type ToolEvent} from "./ToolExecutionCards";
import "./OpenCodeChatDialog.css";
import {Modal} from "./Modal";

export function OpenCodeChatDialog({onClose}:{onClose:()=>void}){
  const [interactive,setInteractive]=useState(false);
  const [waiting,setWaiting]=useState(false);
  const [nextMessage,setNextMessage]=useState("");
  const [saveHistory,setSaveHistory]=useState(false);
  const [history,setHistory]=useState<{id:string;model:string;createdAt:string;messages:string[];output:string;status:string;sessionId?:string}[]>([]);
  const [historyOpen,setHistoryOpen]=useState(false);
  async function loadHistory(){
    try{setHistory(await window.localAgent.listLocalChatHistory?.()??[]);setHistoryOpen(true);}
    catch(error){setStatus("历史读取失败："+String(error));}
  }
  const [model,setModel]=useState("gemma4:31b");
  const [port,setPort]=useState("11434");
  const [profiles,setProfiles]=useState<{id:string;label:string;model:string;port:number;baseUrl:string;context:number;maxOutput:number}[]>([]);
  const [profileId,setProfileId]=useState("");
  async function loadProfiles(){
    try{const rows=await window.localAgent.listSharedLocalProfiles?.()??[];setProfiles(rows);const p=rows.find(p=>p.id===profileId)||rows[0];if(p){setProfileId(p.id);setModel(p.model);setPort(String(p.port));setStatus("已加载 Settings 模型配置");}else{setProfileId("");setStatus("Settings 中没有可用的 Ollama 配置");}}
    catch(error){setStatus("配置读取失败："+String(error));}
  }
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
      if(event.kind==="waiting-input"){setWaiting(true);setStatus("等待下一轮输入");return;}
      if(event.kind==="tool"&&typeof event.payload?.type==="string"){
        setCards(previous=>appendToolEvent(previous,event.payload as ToolEvent));return;
      }
      const label=event.kind==="tool"?event.payload?.type:event.kind==="usage"?"用量已更新":event.kind==="execution-ended"?"执行终态："+event.payload?.outcome:undefined;
      if(label)setProgress(previous=>[...previous.slice(-49),label]);
    });
    return ()=>{offProgress?.();unsubscribe?.();if(running.current)void window.localAgent.cancelLocalChat?.().catch(()=>{});};
  },[]);
  useEffect(()=>{void loadProfiles();},[]);
  async function run(){
    if(running.current||!window.localAgent.runLocalChat)return;
    const number=Number(port);
    if(!profileId||!model.trim()||!prompt.trim()||!Number.isInteger(number)||number<1||number>65535){setStatus("请选择 Settings 中已有的 Ollama 模型并输入消息");return;}
    running.current=true;setBusy(true);setOutput("");setProgress([]);setCards([]);setStatus("正在启动，请选择固定版本 OpenCode EXE");
    try{
      const result=await window.localAgent.runLocalChat({model:model.trim(),port:number,prompt,messages:[prompt,...followups.filter(message=>message.trim())],saveHistory,profileId:profileId||undefined,interactive});
      setStatus(result.outcome==="succeeded"?"对话结束（未独立验证）":result.outcome==="cancelled"||result.outcome==="interrupted"?"已取消或中断":"执行失败："+result.outcome);
    }catch(error){setStatus("执行未确认："+String(error));}
    finally{running.current=false;setBusy(false);setWaiting(false);setNextMessage("");}
  }
  return <Modal className="opencode-chat-modal" title="OpenCode 本地对话实验" busy={busy} onClose={onClose}>
    <p className="modal-description">本地 Ollama · 独立会话 · 暂不支持文件与命令工具</p>
    <form className="oc-form" onSubmit={event=>{event.preventDefault();void run();}}>
      <div className="oc-columns"><aside className="oc-settings"><h3>模型配置</h3>
      <button type="button" disabled={busy||!window.localAgent.listSharedLocalProfiles} onClick={()=>void loadProfiles()}>读取已有模型配置</button>
      <label>已有配置 <select value={profileId} disabled={busy} onChange={e=>{const id=e.target.value;setProfileId(id);const p=profiles.find(p=>p.id===id);if(p){setModel(p.model);setPort(String(p.port));}}}><option value="">请选择已有模型</option>{profiles.map(p=><option key={p.id} value={p.id}>{p.label} · {p.baseUrl}</option>)}</select></label>
      <p>服务地址：{profiles.find(p=>p.id===profileId)?.baseUrl||"未选择"}</p>
      <label className="oc-check"><input type="checkbox" checked={interactive} disabled={busy} onChange={e=>setInteractive(e.target.checked)}/> 即时连续对话</label>
      <label className="oc-check"><input type="checkbox" checked={saveHistory} disabled={busy} onChange={e=>setSaveHistory(e.target.checked)}/> 保存本地历史（明文）</label>
      </aside><section className="oc-conversation"><h3>对话</h3><div className="oc-output"><p role="status">{status}</p><pre aria-label="OpenCode 输出">{output||"发送消息后将在此显示回复。"}</pre>{cards.length>0&&<ToolExecutionCards cards={cards}/>}</div>
      <label>消息 <textarea rows={4} value={prompt} disabled={busy} onChange={e=>setPrompt(e.target.value)}/></label>
      <details className="oc-advanced"><summary>预设多轮消息</summary>{followups.map((message,i)=><label key={i}>第 {i+2} 轮消息 <textarea rows={2} value={message} disabled={busy} onChange={e=>setFollowups(previous=>previous.map((v,j)=>j===i?e.target.value:v))}/><button type="button" disabled={busy} onClick={()=>setFollowups(previous=>previous.filter((_,j)=>j!==i))}>删除</button></label>)}
      <button type="button" disabled={busy||followups.length>=19} onClick={()=>setFollowups(previous=>[...previous,""])}>添加下一轮消息</button></details>

      {waiting&&<section><label>下一轮消息<textarea value={nextMessage} onChange={e=>setNextMessage(e.target.value)}/></label><button type="button" disabled={!nextMessage.trim()} onClick={async()=>{setWaiting(false);try{await window.localAgent.sendLocalChatNext?.(nextMessage);setNextMessage("");setStatus("正在生成");}catch(e){setWaiting(true);setStatus(String(e));}}}>继续发送</button><button type="button" onClick={async()=>{setWaiting(false);try{await window.localAgent.endLocalChat?.();}catch(e){setWaiting(true);setStatus(String(e));}}}>结束会话</button></section>}

      <button type="button" disabled={busy||!window.localAgent.listLocalChatHistory} onClick={()=>void loadHistory()}>查看历史</button>
      {historyOpen&&<section aria-label="历史对话" style={{maxHeight:280,overflow:"auto"}}>{history.length===0?<p>暂无历史</p>:history.map(item=><details key={item.id}><summary>{item.createdAt} · {item.model} · {item.status}</summary><pre style={{whiteSpace:"pre-wrap"}}>{item.messages.join("\n\n")}</pre><pre style={{whiteSpace:"pre-wrap"}}>{item.output}</pre><button type="button" disabled={busy||!window.localAgent.diagnoseHistorySession} onClick={async()=>{setBusy(true);try{const result=await window.localAgent.diagnoseHistorySession?.(item.id);setStatus(result?`原始会话：${result.outcome}；${result.active?"仍活跃":"未活跃"}；仅诊断，不恢复执行`:"已取消诊断");}catch(error){setStatus(String(error));}finally{setBusy(false);}}}>检查原始会话</button></details>)}<button type="button" onClick={()=>setHistoryOpen(false)}>收起历史</button></section>}
      {progress.length>0?<details><summary>执行事件 ({progress.length})</summary><ul aria-label="执行事件">{progress.map((item,i)=><li key={i}>{item}</li>)}</ul></details>:null}
      </section></div>
      <div className="modal-actions">
        <button type="button" disabled={!busy} onClick={()=>{setStatus("正在请求停止");void window.localAgent.cancelLocalChat?.().catch(error=>setStatus(String(error)));}}>停止</button>
        <button type="submit" disabled={busy||!profileId||!prompt.trim()||!window.localAgent.runLocalChat}>发送</button>
        <button type="button" disabled={busy} onClick={onClose}>关闭</button>
      </div>
    </form>
  </Modal>;
}
