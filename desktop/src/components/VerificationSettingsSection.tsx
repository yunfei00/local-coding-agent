import { useState } from "react";

const example=JSON.stringify({files:[
  {path:"data.xlsx",expect:{sheets:["Data"],cells:[{sheet:"Data",address:"B2",value:"=2+3"}]}},
  {path:"report.docx",expect:{contains:["Summary"]}},
  {path:"deck.pptx",expect:{contains:["Overview"],min_items:1}}
]},null,2);

export function VerificationSettingsSection({running}:{running:boolean}){
  const [spec,setSpec]=useState(example);
  const [path,setPath]=useState("acceptance-report.md");
  const [busy,setBusy]=useState(false);
  const [error,setError]=useState("");
  const [result,setResult]=useState("");
  const run=async()=>{
    setBusy(true);setError("");setResult("");
    try{
      const parsed:unknown=JSON.parse(spec);
      if(!parsed||typeof parsed!=="object"||!Array.isArray((parsed as {files?:unknown}).files))
        throw new Error("验收配置必须包含 files 数组");
      if(!path.endsWith(".md"))throw new Error("报告路径必须是 .md 文件");
      const event=await window.localAgent.verificationRequest({spec:parsed,report_path:path});
      const payload=event.payload??{};
      setResult(JSON.stringify(payload,null,2));
      if(payload.ok===false)setError("验收未全部通过，请查看失败明细");
    }catch(e){setError(String(e));}
    finally{setBusy(false);}
  };
  return <div className="settings-section" aria-label="自动验收">
    <h2>交付物自动验收</h2>
    <p>自动检查 Excel、Word、PowerPoint 的文件结构和指定内容，生成中文报告。此项不代表视觉排版或浏览器上传已经验收。</p>
    <div className="settings-field">
      <label htmlFor="verification-spec">验收规则（JSON）</label>
      <textarea id="verification-spec" rows={14} value={spec} disabled={running||busy} onChange={e=>setSpec(e.target.value)} />
      <label htmlFor="verification-report">报告保存路径（项目工作区内，不覆盖现有文件）</label>
      <input id="verification-report" value={path} disabled={running||busy} onChange={e=>setPath(e.target.value)} />
      <button type="button" disabled={running||busy} onClick={()=>void run()}>开始验收并生成报告</button>
    </div>
    {error?<p role="alert">{error}</p>:null}
    {result?<pre style={{whiteSpace:"pre-wrap",maxHeight:400,overflow:"auto"}}>{result}</pre>:null}
  </div>;
}
