import { useCallback, useEffect, useState } from "react";

type Skill = {name:string; description:string; source:string; enabled:boolean};
type Result = {payload?:Record<string,unknown>};

export function SkillsSettingsSection({running}:{running:boolean}) {
  const [items,setItems] = useState<Skill[]>([]);
  const [source,setSource] = useState("");
  const [busy,setBusy] = useState(false);
  const [error,setError] = useState("");
  const [notice,setNotice] = useState("");
  const [detail,setDetail] = useState<{name:string;instructions:string}|null>(null);
  const load = useCallback(async()=>{
    const result:Result = await window.localAgent.skillsRequest("list");
    setItems((result.payload?.skills as Skill[] | undefined) ?? []);
  },[]);
  useEffect(()=>{void load().catch(e=>setError(String(e)));},[load]);
  const run = async (operation:string,payload:Record<string,unknown>={})=>{
    setBusy(true);setError("");setNotice("");
    try {
      const result = await window.localAgent.skillsRequest(operation,payload);
      if (operation==="read") {
        setDetail({name:String(payload.name),instructions:String(result.payload?.instructions??"")});
      } else {
        await load();
        setNotice("操作已完成。技能脚本不会因安装而自动执行。");
      }
    } catch(e) {setError(String(e));}
    finally {setBusy(false);}
  };
  return <div className="settings-section" aria-label="Skills 技能管理">
    <h2>Skills 技能管理</h2>
    <p>兼容 Agent Skills 的 SKILL.md 与旧版 skill.json。技能说明是非可信内容，执行仍受 Agent 权限控制。</p>
    <div className="settings-field">
      <span>安装本地技能目录、ZIP 路径或公开 GitHub 地址</span>
      <input aria-label="技能来源" value={source} disabled={busy||running} placeholder="https://github.com/owner/repo/tree/main/skills/example" onChange={e=>setSource(e.target.value)} />
      <button type="button" disabled={busy||running||!source.trim()} onClick={()=>{if(window.confirm("确认安装此第三方技能？技能可能包含脚本，安装不会自动执行。"))void run("install",{source:source.trim()});}}>安装技能</button>
    </div>
    <button type="button" disabled={busy} onClick={()=>void load().catch(e=>setError(String(e)))}>刷新列表</button>
    {error?<p role="alert">{error}</p>:null}
    {notice?<p role="status">{notice}</p>:null}
    {items.length===0?<p>当前没有可用技能。</p>:null}
    {items.map(item=><div className="settings-field" key={item.name}>
      <strong>{item.name}</strong>
      <small>{item.description} · {item.source==="builtin"?"内置":item.source==="user"?"用户":"项目"} · {item.enabled?"已启用":"已禁用"}</small>
      <div style={{display:"flex",gap:8,flexWrap:"wrap"}}>
        <button type="button" disabled={busy} onClick={()=>void run("read",{name:item.name})}>查看说明</button>
        <button type="button" disabled={busy||running} onClick={()=>void run(item.enabled?"disable":"enable",{name:item.name})}>{item.enabled?"禁用":"启用"}</button>
        {item.source==="project"?<button type="button" disabled={busy||running} onClick={()=>{if(window.confirm("确认卸载项目技能 "+item.name+"？"))void run("uninstall",{name:item.name});}}>卸载</button>:null}
      </div>
    </div>)}
    {detail?<section className="settings-field" aria-label="技能说明">
      <strong>{detail.name} — SKILL.md</strong>
      <pre style={{whiteSpace:"pre-wrap",maxHeight:300,overflow:"auto"}}>{detail.instructions}</pre>
      <button type="button" onClick={()=>setDetail(null)}>关闭说明</button>
    </section>:null}
  </div>;
}
