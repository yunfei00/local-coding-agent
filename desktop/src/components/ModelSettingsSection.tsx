import {useEffect, useState} from "react";
import {Connection, ModelCatalog, ModelProfile, TaskConfig, modelLabel, longTaskBudget} from "../lib/modelCatalog";
import {ModelDiagnosticResult} from "./ModelDiagnosticResult";

export function ModelSettingsSection({threadId = "", running}: {threadId?: string; running: boolean}) {
  const [catalog, setCatalog] = useState<ModelCatalog | null>(null);
  const [config, setConfig] = useState<TaskConfig | null>(null);
  const [chatDefault,setChatDefault] = useState("");
  const [chatVision,setChatVision] = useState("");
  const [modelTests,setModelTests] = useState<Record<string,{vision?:string}>>({});
  const [selected, setSelected] = useState("");
  const [profileId, setProfileId] = useState("");
  const [key, setKey] = useState("");
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [statuses, setStatuses] = useState<Record<string, string>>({});
  const [discovered, setDiscovered] = useState<string[]>([]);
  const [live, setLive] = useState(false);
  const [diagnosing, setDiagnosing] = useState(false);
  const [diagnostic, setDiagnostic] = useState<Record<string, unknown> | null>(null);
  const request = (op: string, payload: Record<string, unknown> = {}) => window.localAgent.taskRequest(threadId, op, payload);
  useEffect(() => {
    let alive = true;
    void request("task.catalog.get").then(event => {
      if (!alive) return;
      const next = event.payload?.catalog as ModelCatalog;
      setCatalog(next); setConfig(event.payload?.config as TaskConfig); setSelected(next.connections[0]?.connection_id ?? "");
      setChatDefault(String(event.payload?.chat_default ?? "")); setChatVision(String(event.payload?.chat_vision ?? ""));
      setModelTests(event.payload?.model_tests as typeof modelTests ?? {});
    }).catch(cause => {if (alive) setError(String(cause));});
    return () => {alive = false;};
  }, [threadId]);
  const action = async (work: () => Promise<void>) => {
    setBusy(true); setError(""); setMessage("");
    try {await work();} catch (cause) {setError(String(cause));} finally {setBusy(false);}
  };
  if (!catalog || !config) return <div role="status">{error || "Loading model connections…"}</div>;
  const connection = catalog.connections.find(c => c.connection_id === selected);
  const profile = catalog.profiles.find(p => p.model_profile_id === profileId);
  const editConnection = (patch: Partial<Connection>) => setCatalog({...catalog, connections:catalog.connections.map(c => c.connection_id === selected ? {...c, ...patch} : c)});
  const editProfile = (patch: Partial<ModelProfile>) => setCatalog({...catalog, profiles:catalog.profiles.map(p => p.model_profile_id === profileId ? {...p, ...patch} : p)});
  const addModel = (name = "new-model") => {
    if (!connection) return;
    if (catalog.profiles.some(p => p.connection_id === selected && p.model_id === name)) {setError("Model already exists on this connection."); return;}
    const p: ModelProfile = {model_profile_id:crypto.randomUUID(), connection_id:selected, model_id:name, display_name:name, max_output_tokens:1024, context_window:null, temperature:null, pricing:null, tool_mode:"auto"};
    setCatalog({...catalog, profiles:[...catalog.profiles, p]}); setProfileId(p.model_profile_id);
  };
  const bound = (id: string) => id === chatDefault || id === chatVision || Object.values(config.roles).some(p => p.model_profile_id === id);
  return <div className="settings-section model-settings">
    <h2>Models and routing</h2><p>Connections and roles are independent of the chat Provider. Save changes here; existing tasks retain their snapshots.</p>
    {error ? <p className="error-banner" role="alert">{error}</p> : null}
    {message ? <p role="status">{message}</p> : null}
    <fieldset disabled={busy || running || diagnosing}>
      <legend>Provider Connections</legend>
      <label className="settings-field">Connection<select aria-label="Model connection" value={selected} onChange={e => {setSelected(e.target.value); setKey(""); setDiscovered([]);}}>{catalog.connections.map(c => <option key={c.connection_id} value={c.connection_id}>{c.display_name} · {c.provider_type}</option>)}</select></label>
      <button onClick={() => {const c: Connection = {connection_id:crypto.randomUUID(), display_name:"New connection", provider_type:"ollama", base_url:"http://127.0.0.1:11434", credential_reference:null, enabled:true}; setCatalog({...catalog, connections:[...catalog.connections,c]}); setSelected(c.connection_id); setKey(""); setDiscovered([]);}}>Add connection</button>
      {connection ? <>
        <label className="settings-field">Connection name<input aria-label="Connection name" value={connection.display_name} onChange={e => editConnection({display_name:e.target.value})} /></label>
        <label className="settings-field">Provider type<select aria-label="Connection provider type" value={connection.provider_type} onChange={e => editConnection({provider_type:e.target.value as Connection["provider_type"]})}><option value="ollama">Ollama (Local)</option><option value="openai_compatible">OpenAI Compatible (API)</option></select></label>
        <label className="settings-field">Base URL<input aria-label="Connection base URL" value={connection.base_url} onChange={e => editConnection({base_url:e.target.value})} /></label>
        <label><input type="checkbox" checked={connection.enabled} onChange={e => editConnection({enabled:e.target.checked})} />Enabled</label>
        {connection.provider_type === "openai_compatible" ? <>
          <label className="settings-field">API key<input aria-label="Connection API key" type="password" autoComplete="off" value={key} onChange={e => setKey(e.target.value)} /></label>
          <p>Credential: {connection.credential_reference || "No key reference"}. Keys stay in OS protected storage, or session memory when unavailable.</p>
          <button onClick={() => void action(async () => {const result = await request("task.credential.set", {connection_id:selected, api_key:key}); const next = {...catalog, connections:catalog.connections.map(c => c.connection_id === selected ? {...c, credential_reference:key ? "connection-" + selected : null} : c)}; await request("task.catalog.update", {catalog:next, config}); setCatalog(next); setKey(""); setMessage("Credential and connection reference saved: " + String(result.payload?.mode));})}>Save / clear connection key</button>
        </> : null}
        <button onClick={() => void action(async () => {
          // Save first so the tested endpoint is exactly the one displayed.
          await request("task.catalog.update", {catalog, config});
          const result = await request("task.connection.test", {connection_id:selected});
          const payload = result.payload ?? {};
          setStatuses(s => ({...s, [selected]:payload.online ? "Connected" : "Unavailable"}));
          setDiscovered(((payload.models ?? []) as Array<{name: string}>).map(m => m.name));
          setMessage(JSON.stringify(payload, null, 2));
        })}>Fetch model list (does not verify capabilities)</button>
        <button onClick={() => {if (catalog.profiles.some(p => p.connection_id === selected)) {setError("Remove this connection's model profiles after rebinding roles first."); return;} setCatalog({...catalog, connections:catalog.connections.filter(c => c.connection_id !== selected)}); setSelected("");}}>Delete connection</button>
        {discovered.map(name => <button key={name} onClick={() => addModel(name)}>Add model: {name}</button>)}
      </> : null}
      <h3>Model Profiles</h3>
      <p>All connections: {catalog.profiles.length} models</p>
      <ul>{catalog.profiles.map(p => <li key={p.model_profile_id}>{modelLabel(catalog,p)} · {statuses[p.connection_id] ?? "Not tested this session"} · Image input {p.supports_vision ? "declared" : "disabled"} · Vision test {modelTests[p.model_profile_id]?.vision || "NOT RUN"}</li>)}</ul>
      <label className="settings-field">Edit model<select aria-label="Edit model profile" value={profileId} onChange={e => setProfileId(e.target.value)}><option value="">Select profile</option>{catalog.profiles.map(p => <option key={p.model_profile_id} value={p.model_profile_id}>{modelLabel(catalog,p)}</option>)}</select></label>
      <button disabled={!connection} onClick={() => addModel()}>Manually add model</button>
      {profile ? <>
        <label className="settings-field">Model ID<input aria-label="Profile model ID" value={profile.model_id} onChange={e => editProfile({model_id:e.target.value})} /></label>
        <label className="settings-field">Display name<input aria-label="Profile display name" value={profile.display_name} onChange={e => editProfile({display_name:e.target.value})} /></label>
        <label className="settings-field">Context window<input aria-label="Profile context window" type="number" value={profile.context_window ?? ""} onChange={e => editProfile({context_window:e.target.value ? Number(e.target.value) : null})} /></label>
        <label className="settings-field">Maximum output tokens<input aria-label="Profile output limit" type="number" value={profile.max_output_tokens ?? 1024} onChange={e => editProfile({max_output_tokens:Number(e.target.value)})} /></label>
        <label className="settings-field">Temperature<input aria-label="Profile temperature" type="number" step="0.1" value={profile.temperature ?? ""} onChange={e => editProfile({temperature:e.target.value ? Number(e.target.value) : null})} /></label>
        <label className="settings-field">Tool compatibility<select value={profile.tool_mode ?? "auto"} onChange={e => editProfile({tool_mode:e.target.value})}><option value="auto">Auto</option><option value="native">Native tools</option><option value="json">JSON compatibility</option></select></label>
        <label className="settings-field"><span>Vision image input</span><input aria-label="Profile supports vision" type="checkbox" checked={profile.supports_vision ?? false} onChange={e => editProfile({supports_vision:e.target.checked})} /><small>仅为支持图像的模型启用。截图默认保存在本机；每次授权发送截图时，在线模型服务可能收到图像。</small></label>
        {(["input_price", "output_price"] as const).map(k => <label className="settings-field" key={k}>{k} per million tokens<input aria-label={"Profile " + k} type="number" step="0.01" value={profile.pricing?.[k] ?? ""} onChange={e => editProfile({pricing:{...profile.pricing, [k]:e.target.value ? Number(e.target.value) : undefined}})} /></label>)}
        <button onClick={() => {if (bound(profileId)) {setError("Rebind all roles using this model before deletion."); return;} setCatalog({...catalog, profiles:catalog.profiles.filter(p => p.model_profile_id !== profileId)}); setProfileId("");}}>Delete model profile</button>
      </> : null}
      <h3>Role Routing</h3>
      <p>Chat 与 Task 独立选择模型；Single Agent 只需要配置 Executor。</p>
      <label>Default Task Vision Observer<select aria-label="Default Task Vision Observer" value={config.vision_profile_id || ""} onChange={e=>setConfig({...config,vision_profile_id:e.target.value || null})}><option value="">Executor vision / UIA</option>{catalog.profiles.filter(p=>p.supports_vision).map(p=><option key={p.model_profile_id} value={p.model_profile_id}>{modelLabel(catalog,p)}</option>)}</select></label>
      <label>Default Chat Model<select aria-label="Default Chat profile" value={chatDefault} onChange={e=>setChatDefault(e.target.value)}><option value="">Migrated legacy default</option>{catalog.profiles.map(p=><option key={p.model_profile_id} value={p.model_profile_id}>{modelLabel(catalog,p)}</option>)}</select></label>
      <label>Chat Vision Observer<select aria-label="Chat Vision Observer" value={chatVision} onChange={e=>setChatVision(e.target.value)}><option value="">Use Chat model / UIA</option>{catalog.profiles.filter(p=>p.supports_vision).map(p=><option key={p.model_profile_id} value={p.model_profile_id}>{modelLabel(catalog,p)}</option>)}</select></label>
      {Object.entries(config.roles).map(([role, binding]) => <label className="settings-field" key={role}>{role} Model<select aria-label={role + " profile"} value={binding.model_profile_id ?? ""} onChange={e => setConfig({...config, roles:{...config.roles, [role]:{...binding, model_profile_id:e.target.value}}})}><option value="">Legacy / not configured</option>{catalog.profiles.map(p => <option key={p.model_profile_id} value={p.model_profile_id}>{modelLabel(catalog,p)}</option>)}</select></label>)}
      <h3>Execution Policy</h3>
      <select aria-label="Default execution policy" value={config.strategy} onChange={e => setConfig({...config, strategy:e.target.value})}><option value="single-agent">Single Agent (online)</option><option value="local-first">Local-first</option><option value="local-only">Local-only</option><option value="api-only">API-only</option></select>
      <p>Single Agent requires only one online Executor profile. It calls tools directly, without a separate Planner, Reviewer or escalation model.</p>
      <p>Local-only and API-only reject incompatible bindings. No silent fallback. Local-first defaults to local planning, execution and review with API escalation.</p>
      <h3>API Budget</h3>
      <button onClick={() => setConfig(longTaskBudget(config))}>Use long task budget</button>
      <p>长任务额度：每任务至少 200 次 API、1,000 万 Token、2 小时；全局至少 2,000 次、1 亿 Token。可能增加费用。保存后用于新任务；保留费用上限、重试和停止保护。</p>
      <p>0 in api_calls or api_tokens explicitly disables API calls; changing strategy preserves these values. Global limits include earlier tasks across restarts. New tasks use saved Settings; existing tasks retain their snapshots.</p>
      {Object.entries(config.budget).map(([k,v]) => <label className="settings-field" key={k}>{k}<input aria-label={"Default " + k} type="number" min="0" value={v ?? ""} onChange={e => setConfig({...config, budget:{...config.budget, [k]:e.target.value ? Number(e.target.value) : null}})} /></label>)}
      <p>Caps use conservative reservations and request output limits; provider tokenization and billing may differ. Failed requests retain reservations. Cost caps require configured prices.</p>
      <button onClick={() => void action(async () => {const result = await request("task.catalog.update", {catalog, config,chat_default:chatDefault,chat_vision:chatVision}); setCatalog(result.payload?.catalog as ModelCatalog); setConfig(result.payload?.config as TaskConfig); setMessage("Model configuration saved. Running task snapshots are unchanged.");})}>Save model configuration</button>
    </fieldset>
    <section aria-label="Model connection diagnostics">
      <h3>Connection diagnostics</h3>
      <p>请选择已保存的模型。默认仅检查配置，不发送请求。Vision 标志是声明，实测结果单独显示。</p>
      <label><input aria-label="Enable Live Test" type="checkbox" checked={live} disabled={diagnosing} onChange={e => setLive(e.target.checked)} />Live Test：授权付费请求，最多 3 次、1 张合成图片；不上传桌面。每次最长 60 秒，无自动重试。</label>
      {[false,true].map(vision => <button key={String(vision)} disabled={diagnosing || running || !profile || profile.connection_id !== selected} onClick={() => {
        setDiagnosing(true); setDiagnostic(null); setError("");
        void (async () => {
          const saved = (await request("task.catalog.get")).payload?.catalog as ModelCatalog;
          if (JSON.stringify(saved.profiles.find(p => p.model_profile_id === profileId)) !== JSON.stringify(profile) || JSON.stringify(saved.connections.find(c => c.connection_id === selected)) !== JSON.stringify(connection)) throw new Error("Save model configuration before testing changed fields.");
          const event = await request("task.model.diagnostic", {connection_id:selected, model_profile_id:profileId, live, vision});
          setDiagnostic(event.payload ?? {});
        })().catch(cause => setError(String(cause))).finally(() => setDiagnosing(false));
      }}>{vision ? "Test Vision" : "Test Connection"}</button>)}
      {diagnosing ? <><span role="status">Diagnosing…</span><button onClick={() => void request("task.model.diagnostic.cancel", {connection_id:selected})}>Stop diagnostics</button></> : null}
      {diagnostic ? <ModelDiagnosticResult report={diagnostic} /> : null}
    </section>
  </div>;
}
