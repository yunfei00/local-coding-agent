import { useState } from "react";

type ElementInfo={index:number;tag:string;text:string;role?:string;aria_label?:string;placeholder?:string;type?:string};
type Snapshot={session_id?:string;url?:string;title?:string;text?:string;elements?:ElementInfo[]};
export function BrowserSettingsSection({running}:{running:boolean}) {
  const [url,setUrl]=useState("https://example.com");
  const [session,setSession]=useState("");
  const [selector,setSelector]=useState("");
  const [value,setValue]=useState("");
  const [operation,setOperation]=useState("click");
  const [snapshot,setSnapshot]=useState<Snapshot|null>(null);
  const [busy,setBusy]=useState(false);
  const [error,setError]=useState("");
  const [history,setHistory]=useState<string[]>([]);
  const [screenshotPath,setScreenshotPath]=useState("browser-screenshot.png");
  const request=async(op:string,extra:Record<string,unknown>={})=>{
    setBusy(true);setError("");
    try {
      const interactive=["click","press","check","uncheck","select"].includes(op);
      if(interactive&&!window.confirm("浏览器操作可能提交表单或改变网站数据。确认执行 "+op+"？"))return;
      const event=await window.localAgent.browserRequest({operation:op,session_id:session,...extra,confirmed:interactive});
      const result=event.payload??{};
      if(result.ok===false)throw new Error(String(result.summary??"浏览器操作失败"));
      const data=(result.data??{}) as Snapshot & {closed?:boolean};
      if(op==="open")setSession(String(data.session_id??""));
      if(op==="close"){setSession("");setSnapshot(null);}
      else setSnapshot(data);
      setHistory(old=>[...old.slice(-19),op+"："+String(data.url??session)]);
    }catch(e){setError(String(e));}
    finally{setBusy(false);}
  };
  const disabled=busy||running;
  return <div className="settings-section" aria-label="浏览器自动化">
    <h2>浏览器自动化</h2>
    <p>使用隔离的 Chromium 浏览器访问公开网页。禁止下载、内网地址和跨站请求。网页内容不可信，提交操作需要确认。</p>
    <div className="settings-field">
      <label htmlFor="browser-url">网址</label>
      <input id="browser-url" value={url} disabled={disabled} onChange={e=>setUrl(e.target.value)} placeholder="https://example.com" />
      <div style={{display:"flex",gap:8,flexWrap:"wrap"}}>
        <button type="button" disabled={disabled} onClick={()=>void request("open",{url})}>打开新会话</button>
        <button type="button" disabled={disabled||!session} onClick={()=>void request("navigate",{value:url})}>访问网址</button>
        <button type="button" disabled={disabled||!session} onClick={()=>void request("snapshot")}>刷新 DOM</button>
        <button type="button" disabled={disabled||!session} onClick={()=>void request("back")}>后退</button>
        <button type="button" disabled={disabled||!session} onClick={()=>void request("forward")}>前进</button>
        <button type="button" disabled={disabled||!session} onClick={()=>void request("scroll",{value:"600"})}>向下滚动</button>
        <button type="button" disabled={disabled||!session} onClick={()=>void request("tables")}>提取表格</button>
        <button type="button" disabled={disabled||!session} onClick={()=>void request("close")}>关闭会话</button>
      </div>
    </div>
    {session?<p>当前会话：<code>{session}</code></p>:null}
    <div className="settings-field">
      <label htmlFor="browser-selector">CSS 选择器（必须唯一匹配）</label>
      <input id="browser-selector" value={selector} disabled={disabled||!session} onChange={e=>setSelector(e.target.value)} placeholder="button[type=submit]" />
      <label htmlFor="browser-value">输入内容 / 按键 / 下拉选项</label>
      <input id="browser-value" value={value} disabled={disabled||!session} onChange={e=>setValue(e.target.value)} />
      <select aria-label="浏览器操作" value={operation} disabled={disabled||!session} onChange={e=>setOperation(e.target.value)}>
        {["click","fill","select","check","uncheck","press","wait"].map(op=><option key={op} value={op}>{op}</option>)}
      </select>
      <button type="button" disabled={disabled||!session||(operation!=="wait"&&!selector)} onClick={()=>void request(operation,{selector,value})}>执行操作</button>
    </div>
    <div className="settings-field">
      <label htmlFor="browser-screenshot">截图保存路径（工作区内，新文件）</label>
      <input id="browser-screenshot" value={screenshotPath} onChange={e=>setScreenshotPath(e.target.value)} disabled={disabled||!session} />
      <button type="button" disabled={disabled||!session||!screenshotPath} onClick={()=>void request("screenshot",{path:screenshotPath})}>保存 PNG 截图</button>
    </div>
    {error?<p role="alert">{error}</p>:null}
    {snapshot?<section className="settings-field">
      <strong>{snapshot.title||"网页快照"}</strong>
      <small>{snapshot.url}</small>
      <p>可交互元素（最多 100 项）</p>
      <div style={{maxHeight:180,overflow:"auto"}}>{(snapshot.elements??[]).map(el=><p key={el.index}><code>{el.tag}</code> {el.text||el.aria_label||el.placeholder||el.type||"(无文字)"}</p>)}</div>
      <p>页面文本（最多 50000 字符）</p>
      <pre style={{whiteSpace:"pre-wrap",maxHeight:300,overflow:"auto"}}>{snapshot.text}</pre>
    </section>:null}
    {history.length>0?<section><strong>操作记录</strong><pre style={{whiteSpace:"pre-wrap"}}>{history.join("\n")}</pre></section>:null}
  </div>;
}
