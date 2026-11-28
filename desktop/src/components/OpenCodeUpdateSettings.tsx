import {useEffect, useState} from "react";

export function OpenCodeUpdateSettings() {
  const [current,setCurrent]=useState("");
  const [latest,setLatest]=useState<string|null>(null);
  const [message,setMessage]=useState("");
  const [busy,setBusy]=useState(false);
  useEffect(()=>{
    let mounted=true;
    void window.localAgent.getEngineStatus?.().then(status=>{
      if (mounted) setCurrent(status.engines.find(engine=>engine.id==="opencode")?.version ?? "");
    }).catch(()=>{});
    return ()=>{mounted=false;};
  },[]);

  async function action(kind:"check"|"install"|"restore") {
    setBusy(true);
    setMessage("");
    try {
      if (kind==="check") {
        const result=await window.localAgent.checkOpenCodeUpdate();
        setCurrent(result.current);
        setLatest(result.latest);
        setMessage(result.latest ? `发现 ${result.latest}` : "当前已是可用版本");
      } else {
        const result=kind==="install" ? await window.localAgent.installOpenCodeUpdate() : await window.localAgent.restoreBundledOpenCode();
        setCurrent(result.current);
        setLatest(null);
      }
    } catch (error) { setMessage(String(error)); }
    finally { setBusy(false); }
  }

  return <section className="context-section"><h3>OpenCode 运行时</h3>
    <p>当前版本 {current || "未确认"}</p>
    <button disabled={busy} onClick={()=>void action("check")}>检查引擎更新</button>
    {latest ? <button disabled={busy} onClick={()=>void action("install")}>校验并升级 {latest}</button> : null}
    <button disabled={busy} onClick={()=>void action("restore")}>回到内置版本</button>
    {message ? <p role="status">{message}</p> : null}
  </section>;
}
