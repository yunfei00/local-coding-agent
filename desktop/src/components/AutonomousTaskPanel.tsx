import {useEffect, useState} from "react";
import {RecentExecutions} from "./RecentExecutions";
import {TaskEvidence} from "./TaskEvidence";
import {mergeTaskSnapshot, TaskSnapshot, taskIsActive} from "../lib/autonomousTask";
import {TaskConfig as Config, ModelCatalog, modelLabel, taskConfigOverrides, longTaskBudget} from "../lib/modelCatalog";

export function AutonomousTaskPanel({threadId, ensureThread, running, onClose, onSettings}: {
  threadId: string; ensureThread?: (goal:string) => Promise<string>; running: boolean; onClose: () => void; onSettings: () => void;
}) {
  const [tasks, setTasks] = useState<TaskSnapshot[]>([]);
  const [config, setConfig] = useState<Config | null>(null);
  const [savedConfig, setSavedConfig] = useState<Config | null>(null);
  const [catalog, setCatalog] = useState<ModelCatalog>({connections:[], profiles:[]});
  const [goal, setGoal] = useState("");
  const [commands, setCommands] = useState("");
  const [busy, setBusy] = useState(false);
  const [stopping, setStopping] = useState(false);
  const [diagnostic, setDiagnostic] = useState<{json:Record<string,unknown>; markdown:string} | null>(null);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [model, setModel] = useState("");
  const [globalUsage, setGlobalUsage] = useState<Record<string, unknown>>({});
  const [advanced, setAdvanced] = useState("");
  const apply = (event: AgentEnvelope, owner = threadId) => {
    const next = event.payload?.task as TaskSnapshot | undefined;
    if (next) setTasks(current => mergeTaskSnapshot(current, next, owner));
    const list = event.payload?.tasks as TaskSnapshot[] | undefined;
    if (list) setTasks(current => list.reduce((all, task) => mergeTaskSnapshot(all, task, owner), current));
  };
  const request = async (operation: string, payload: Record<string, unknown> = {}) => {
    setBusy(true); setError("");
    try {
      const owner = !threadId && operation === "task.start" && ensureThread ? await ensureThread(String(payload.goal ?? "")) : threadId;
      const event = await window.localAgent.taskRequest(owner, operation, payload);
      apply(event, owner);
      return event;
    } catch (cause) {setError(String(cause)); return null;}
    finally {setBusy(false);}
  };
  useEffect(() => {
    let alive = true;
    setTasks([]); setNotice(""); setModel(""); setDiagnostic(null);
    void window.localAgent.taskRequest(threadId, "task.catalog.get").then(event => {
      if (!alive) return;
      const next = event.payload?.config as Config;
      setCatalog(event.payload?.catalog as ModelCatalog);
      setConfig(next); setSavedConfig(next); setCommands(next.verification_commands.join("\n"));
      setAdvanced(JSON.stringify(next, null, 2));
      setGlobalUsage(event.payload?.global_usage as Record<string, unknown> ?? {});
    }).catch(cause => {if (alive) setError(String(cause));});
    if (threadId) void window.localAgent.taskRequest(threadId, "task.list").then(event => {if (alive) apply(event);}).catch(cause => {if (alive) setError(String(cause));});
    const unsubscribe = window.localAgent.onAgentEvent(event => {
      if (event.type === "connection.restored" && alive && threadId) {
        void window.localAgent.taskRequest(threadId,"task.list").then(next => {if (alive) apply(next);}).catch(cause => {if (alive) setError(String(cause));});
        return;
      }
      if (event.thread_id !== threadId || !alive) return;
      if (event.type === "task.updated") apply(event);
      if (["tool.completed","turn.continuing","execution.updated"].includes(event.type)) {
        void window.localAgent.taskRequest(threadId,"task.list").then(next => {if (alive) apply(next);}).catch(() => {});
      }
      if (event.type === "model.active") setModel(String(event.payload?.role) + " · " + String(event.payload?.provider ?? event.payload?.route) + " / " + String(event.payload?.model));
      if (event.type === "model.compatibility") setNotice(String(event.payload?.message));
      if (event.type === "verification.progress") setNotice("GUI 验收 · " + String(event.payload?.stage) + " · " + String(event.payload?.state));
    });
    return () => {alive = false; unsubscribe();};
  }, [threadId]);
  const currentConfig = () => config && ({...config, verification_commands: commands.split("\n").map(c => c.trim()).filter(Boolean)});
  const start = async () => {
    const edited = currentConfig();
    if (!savedConfig || !edited) return;
    const event = await request("task.start", {goal, config_overrides:taskConfigOverrides(savedConfig, edited)});
    const effective = (event?.payload?.task as {config?:Config} | undefined)?.config;
    if (effective) {
      setConfig(effective); setSavedConfig(event?.payload?.defaults as Config);
      setCatalog(event?.payload?.catalog as ModelCatalog); setGlobalUsage(event?.payload?.global_usage as Record<string, unknown>);
      setCommands(effective.verification_commands.join("\n"));
    }
  };
  const activeTask = tasks.find(taskIsActive);
  const interrupt = async (operation:string) => {
    if (!activeTask || stopping) return;
    setStopping(true); setError("");
    try {apply(await window.localAgent.taskRequest(threadId, operation, {task_id:activeTask.id}));}
    catch (cause) {setError(String(cause));}
    finally {setStopping(false);}
  };
  const resume = async (task: TaskSnapshot, localOnly = false) => {
    if (!window.confirm("恢复前请检查任务工作区、代码差异及检查点。已完成操作将保留，状态不明的 API 调用额度仍计入用量。确认继续？")) return;
    await request("task.resume", {task_id:task.id, confirm_workspace:true, local_only:localOnly});
  };
  return <aside className="context-overlay" aria-label="Autonomous task">
    <div className="context-panel task-panel">
      <header className="context-panel-header"><div><span className="eyebrow">自主编码</span><h2>自主任务</h2></div><button className="panel-close" onClick={onClose}>关闭</button></header>
      {activeTask ? <div className="task-live-controls" role="status"><strong>{activeTask.status}</strong><span>Task {activeTask.id.slice(0,12)}</span><button disabled={stopping} onClick={() => void interrupt("task.pause")}>暂停当前任务</button><button className="stop-button" disabled={stopping} onClick={() => void interrupt("task.cancel")}>{stopping ? "正在停止…" : "取消当前任务"}</button></div> : null}
      {error ? <div className="error-banner">{error}</div> : null}
      {notice ? <p role="status">{notice}</p> : null}
      {model ? <p className="task-model" role="status">{model}</p> : null}
      {config ? <section className="context-section">
        <label>任务策略<select aria-label="任务策略" value={config.strategy} disabled={running} onChange={e => setConfig({...config, strategy:e.target.value})}>
          <option value="single-agent">单智能体（在线模型）</option><option value="local-first">本地优先</option><option value="local-only">仅本地模型</option><option value="api-only">仅在线 API</option>
        </select></label>
        <p>{config.strategy === "single-agent" ? "单智能体仅使用在线执行模型进行推理和工具调用，无需单独配置规划、复核或本地模型。请在下方选择在线执行模型并预留足够的调用额度。" : "Strategy validates the saved role bindings. For 仅在线 API, choose API profiles for Planner, Executor and Reviewer. Existing tasks keep their configuration snapshot."}</p>
        <p>新任务使用最新保存的设置及此处修改的参数；已有任务保持原配置。切换策略不会自动修改设为零的额度。</p>
        <p>任务获得授权后在隔离的 Git 工作区修改代码，不会自动提交、推送或合并。</p>
        <textarea aria-label="Autonomous task goal" placeholder="请描述需要完成的开发任务…" value={goal} onChange={e => setGoal(e.target.value)} />
        <label>验收命令（每行一条；留空则自动识别项目）<textarea aria-label="Verification commands" value={commands} onChange={e => setCommands(e.target.value)} /></label>
        <button disabled={busy || running || !goal.trim()} onClick={() => void start()}>启动自主任务</button>
        <details><summary>模型与预算</summary>
          <details><summary>图形界面验收配置</summary><p>在任务开始前固定启动命令、精确窗口标题和 desktop_* 控件断言。每轮独立启动、截图和清理；默认 UI Automation。可选 vision_profile_id 只提供视觉观察，每次上传仍需授权。</p>
            <textarea aria-label="图形界面验收配置" key={JSON.stringify(config.gui_verification)} defaultValue={config.gui_verification ? JSON.stringify(config.gui_verification,null,2) : ""} placeholder={'{"command":"npm start","window_title":"My App","steps":[{"tool":"desktop_wait","arguments":{"selector":{"automation_id":"StatusLabel"},"state":"name","expected":"Settings ready"}}]}'} onBlur={e => {try {setConfig({...config,gui_verification:e.target.value.trim() ? JSON.parse(e.target.value) : null});} catch {setError("图形界面验收配置必须是有效的 JSON");}}} />
          </details>
          <label>任务视觉观察模型<select aria-label="任务视觉观察模型" value={config.vision_profile_id !== undefined ? config.vision_profile_id || "" : String(config.gui_verification?.vision_profile_id || "")} onChange={e=>setConfig({...config,vision_profile_id:e.target.value || null})}><option value="">执行模型视觉能力 / UI 自动化</option>{catalog.profiles.filter(p=>p.supports_vision).map(p=><option key={p.model_profile_id} value={p.model_profile_id}>{modelLabel(catalog,p)}</option>)}</select></label>
          <button onClick={onSettings}>连接地址与 API 密钥设置</button>
          {(["local", "api"] as const).map(route => <button key={route} disabled={busy} onClick={() => void request("task.connection.test", {route}).then(event => {if (event) setNotice(JSON.stringify(event.payload, null, 2));})}>测试 {route === "local" ? "本地" : "在线"}连接</button>)}
          {Object.entries(config.roles).filter(([role]) => config.strategy !== "single-agent" || role === "executor").map(([role, profile]) => <div className="task-role" key={role}>
            <label>{role}<select aria-label={role + " task profile"} value={profile.model_profile_id ?? ""} onChange={e => setConfig({...config, roles:{...config.roles, [role]:{...profile, model_profile_id:e.target.value}}})}><option value="">Legacy: {profile.model || "Not configured"}</option>{catalog.profiles.map(p => <option key={p.model_profile_id} value={p.model_profile_id}>{modelLabel(catalog,p)}</option>)}</select></label>
          </div>)}
          <button disabled={busy || running} onClick={() => setConfig(longTaskBudget(config))}>使用长任务预算</button>
          <p>长任务额度：每任务至少 200 次 API、1,000 万 Token、2 小时；全局至少 2,000 次、1 亿 Token。可能增加费用。新任务直接使用；暂停任务需应用配置。保留已用额度、费用上限和循环保护。</p>
          {Object.entries(config.budget).map(([key, value]) => <label key={key}>{key}<input aria-label={key} type="number" min="0" value={value ?? ""} placeholder="不限制费用" onChange={e => setConfig({...config, budget:{...config.budget, [key]:e.target.value === "" ? null : Number(e.target.value)}})} /></label>)}
          <p>全局用量包含历史任务及重启前的累计值：API 调用 {String(globalUsage.api_calls ?? 0)}, 预留 Token {String(globalUsage.reserved_tokens ?? 0)}.</p>
          <p>Token 与费用上限按保守估算预留；不同服务商的计费方式可能不同。状态不明的请求仍保留预留额度。价格按每百万 Token 计。</p>
          <button disabled={busy || running} onClick={() => void request("task.settings.update", {config:currentConfig()}).then(event => {if (event) {setSavedConfig(event.payload?.config as Config); setNotice("任务默认配置已保存，正在运行的任务仍使用原配置快照。");}})}>保存任务默认配置</button>
          <details><summary>高级设置：角色限制、工具兼容性与价格</summary>
            <button onClick={() => setAdvanced(JSON.stringify(currentConfig(), null, 2))}>加载当前配置</button>
            <textarea aria-label="Advanced task configuration" className="task-json" value={advanced} onChange={e => setAdvanced(e.target.value)} />
            <button disabled={busy || running} onClick={() => {
              try {const next = JSON.parse(advanced) as Config; void request("task.settings.update", {config:next}).then(event => {if (event) {setConfig(event.payload?.config as Config); setSavedConfig(event.payload?.config as Config); setCommands(next.verification_commands.join("\n"));}});} catch (cause) {setError(String(cause));}
            }}>校验并保存配置</button>
          </details>
        </details>
      </section> : <p>正在加载任务配置…</p>}
      {tasks.map(task => <section className="context-section" key={task.id}>
        <h3>{task.goal}</h3><strong data-task-status={task.status}>{task.status}</strong><p>{task.reason}</p>
        {task.last_error ? <p role="alert">{task.last_error.code} — open 任务诊断 for the request and parsing details.</p> : null}
        {task.last_error?.budget ? <div role="alert" aria-label="Budget rejection details"><strong>{task.last_error.budget.scope} / {task.last_error.budget.field}</strong><p>Limit {task.last_error.budget.limit} · Used/reserved {task.last_error.budget.used} · This request {task.last_error.budget.required} · 剩余 {task.last_error.budget.remaining}</p><p>Request Token estimate: input {task.last_error.budget.input_token_estimate} + output limit {task.last_error.budget.output_limit} = {task.last_error.budget.request_token_reservation}. No API request sent. Global usage includes other tasks.</p><p>Review the named field in Settings → 模型与预算 and the model output limit. Saved Settings apply to new tasks. To change this paused snapshot, review the configuration above and explicitly apply it. Usage is retained.</p><button onClick={onSettings}>检查已保存的模型和预算设置</button></div> : null}
        <p>{task.config?.strategy === "single-agent" ? "单智能体 · 在线执行模型 · 无独立规划请求" : `规划尝试 ${task.planning_attempts ?? 0} / ${task.config?.budget.planning_attempts ?? 4}`}</p>
        <button onClick={() => void window.localAgent.taskRequest(threadId, "task.diagnostics", {task_id:task.id}).then(event => setDiagnostic(event.payload?.diagnostics as typeof diagnostic)).catch(cause => setError(String(cause)))}>任务诊断 {task.id.slice(0,8)}</button>
        <p>尝试 {task.attempts} · 修复 {task.repairs} · 升级 {task.escalations} · {Math.round(task.elapsed_seconds)}s</p>
        <p>API {task.usage.api_calls} · 本地 {task.usage.local_calls} · 预留 Token {task.usage.reserved_tokens}</p>
        {task.config ? <p>API 调用：{task.usage.api_calls} / {task.config.budget.api_calls} · API Token 预留：{task.usage.reserved_tokens} / {task.config.budget.api_tokens} · 剩余 {Math.max(0, Number(task.config.budget.api_tokens) - task.usage.reserved_tokens)}</p> : null}
        {task.calls?.length ? <details><summary>模型调用记录</summary>{task.calls.map(call => <p key={call.id}>[{new Date(call.created_at * 1000).toLocaleTimeString()}] #{call.usage.sequence} · {call.id.slice(0,8)} · {call.usage.phase} / {call.role} · {call.usage.provider || call.route} / {call.model} · {call.status} {call.usage.http_status ? `HTTP ${call.usage.http_status}` : ""} {call.usage.error_code || ""} {call.usage.schema_valid !== undefined && call.usage.schema_valid !== null ? `结构校验 ${call.usage.schema_valid ? "通过" : "失败"}` : ""} {call.usage.next_state ? `→ ${call.usage.next_state}` : ""}</p>)}</details> : null}
        <p>API 输入 {task.usage.input_tokens} · 输出 {task.usage.output_tokens} · 缓存 {task.usage.cached_tokens} {task.usage.estimated ? "（估算）" : "（服务商返回）"}</p>
        <p>验收轮次 {task.attempts} · 自动修复 {task.repairs}</p>
        <TaskEvidence task={task} />
        {task.verification_history?.length ? <details><summary>独立验收与自动修复记录</summary>{task.verification_history.map(round => <div key={round.attempt}><strong>#{round.attempt} {round.passed ? "通过" : "失败"}</strong>{round.results.filter(r => !r.ok).map((r,i) => <pre key={i}>{r.command + ": " + r.summary}</pre>)}</div>)}</details> : null}
        {task.report.gui_verification ? <p>GUI acceptance: {task.report.gui_verification}</p> : null}
        <p>预留费用 {task.usage.reserved_cost.toFixed(6)} · 实际 {task.usage.actual_cost_known ? task.usage.actual_cost.toFixed(6) : "不可用"}</p>
        <details><summary>用量精度</summary><p>{task.usage.precision}</p></details>
        {taskIsActive(task) ? <><button disabled={busy} onClick={() => void request("task.pause", {task_id:task.id})}>暂停任务</button><button disabled={busy} onClick={() => void request("task.cancel", {task_id:task.id})}>停止任务</button></> : <>
          {["paused","failed","awaiting_approval"].includes(task.status) ? <button disabled={busy} onClick={() => void request("task.cancel", {task_id:task.id})}>取消任务</button> : null}
          <button disabled={busy || running} onClick={() => void resume(task)}>恢复 / 继续</button>
          {task.config?.strategy !== "single-agent" ? <button disabled={busy || running} onClick={() => void resume(task, true)}>仅本地模型继续</button> : null}
        </>}
        {task.status === "paused" ? <><button disabled={busy} onClick={() => {
          const raw = window.prompt('Explicit task budget update, e.g. {"api_calls":4,"api_tokens":40000}');
          if (!raw) return;
          try {void request("task.budget.add", {task_id:task.id, budget:JSON.parse(raw)});} catch (cause) {setError(String(cause));}
        }}>增加任务预算</button><button disabled={busy || running} onClick={() => {
          if (window.confirm("Apply the model strategy, verification commands and budget currently shown above to this paused task? Provider addresses also refresh from Settings. Existing usage remains charged.")) void request("task.configure", {task_id:task.id, config:currentConfig()});
        }}>将配置应用到暂停任务</button></> : null}
        <details><summary>任务计划与检查点</summary><ol>{task.plan.steps.map(step => <li key={step.id}>{step.description} — {step.state}</li>)}</ol><p>隔离工作区：{task.workspace || "等待隔离工作区授权"}<br />分支：{task.branch}</p></details>
        <RecentExecutions calls={task.plan.steps.flatMap(s => s.executions ?? [])} />
        {task.verification.map((test, i) => <details key={i}><summary>{test.ok ? "通过" : "失败"} · {test.command || "未配置验收命令"} · {test.category} · exit {test.exit_code ?? "—"} · {test.duration_ms}ms</summary><pre>{test.summary}</pre><p>完整日志：{test.log_path}</p></details>)}
        {task.report.review ? <details><summary>完成报告与 Git 审查</summary><p>{task.report.review}</p><p>{task.report.git_approval}</p><pre>{task.report.diff || "无已跟踪文件差异"}</pre><button onClick={() => void window.localAgent.copyText(JSON.stringify(task, null, 2))}>复制任务报告</button></details> : null}
        {task.status === "awaiting_approval" ? <button disabled={busy || running} onClick={() => void request("task.approve", {task_id:task.id})}>接受已验证报告</button> : null}
      </section>)}
      {diagnostic ? <section className="context-section" aria-label="任务诊断 report"><h3>任务诊断</h3><p>诊断信息不包含提示词、用户文件内容和密钥；报告同时保存在应用数据目录。</p><button onClick={() => void window.localAgent.copyText(JSON.stringify(diagnostic.json, null, 2))}>复制诊断 JSON</button><button onClick={() => void window.localAgent.copyText(diagnostic.markdown)}>复制诊断 Markdown</button><pre className="task-json">{JSON.stringify(diagnostic.json, null, 2)}</pre></section> : null}
    </div>
  </aside>;
}
