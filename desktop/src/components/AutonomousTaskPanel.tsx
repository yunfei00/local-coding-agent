import {useEffect, useState} from "react";
import {mergeTaskSnapshot, TaskSnapshot, taskIsActive} from "../lib/autonomousTask";
import {TaskConfig as Config, ModelCatalog, modelLabel} from "../lib/modelCatalog";

export function AutonomousTaskPanel({threadId, running, onClose, onSettings}: {
  threadId: string; running: boolean; onClose: () => void; onSettings: () => void;
}) {
  const [tasks, setTasks] = useState<TaskSnapshot[]>([]);
  const [config, setConfig] = useState<Config | null>(null);
  const [catalog, setCatalog] = useState<ModelCatalog>({connections:[], profiles:[]});
  const [goal, setGoal] = useState("");
  const [commands, setCommands] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [model, setModel] = useState("");
  const [globalUsage, setGlobalUsage] = useState<Record<string, unknown>>({});
  const [advanced, setAdvanced] = useState("");
  const apply = (event: AgentEnvelope) => {
    const next = event.payload?.task as TaskSnapshot | undefined;
    if (next) setTasks(current => mergeTaskSnapshot(current, next, threadId));
    const list = event.payload?.tasks as TaskSnapshot[] | undefined;
    if (list) setTasks(current => list.reduce((all, task) => mergeTaskSnapshot(all, task, threadId), current));
  };
  const request = async (operation: string, payload: Record<string, unknown> = {}) => {
    setBusy(true); setError("");
    try {
      const event = await window.localAgent.taskRequest(threadId, operation, payload);
      apply(event);
      return event;
    } catch (cause) {setError(String(cause)); return null;}
    finally {setBusy(false);}
  };
  useEffect(() => {
    let alive = true;
    setTasks([]); setNotice(""); setModel("");
    void window.localAgent.taskRequest(threadId, "task.catalog.get").then(event => {
      if (!alive) return;
      const next = event.payload?.config as Config;
      setCatalog(event.payload?.catalog as ModelCatalog);
      setConfig(next); setCommands(next.verification_commands.join("\n"));
      setAdvanced(JSON.stringify(next, null, 2));
      setGlobalUsage(event.payload?.global_usage as Record<string, unknown> ?? {});
    }).catch(cause => {if (alive) setError(String(cause));});
    void window.localAgent.taskRequest(threadId, "task.list").then(event => {if (alive) apply(event);}).catch(cause => {if (alive) setError(String(cause));});
    const unsubscribe = window.localAgent.onAgentEvent(event => {
      if (event.thread_id !== threadId || !alive) return;
      if (event.type === "task.updated") apply(event);
      if (event.type === "model.active") setModel(String(event.payload?.role) + " · " + String(event.payload?.provider ?? event.payload?.route) + " / " + String(event.payload?.model));
      if (event.type === "model.compatibility") setNotice(String(event.payload?.message));
    });
    return () => {alive = false; unsubscribe();};
  }, [threadId]);
  const currentConfig = () => config && ({...config, verification_commands: commands.split("\n").map(c => c.trim()).filter(Boolean)});
  const resume = async (task: TaskSnapshot, localOnly = false) => {
    if (!window.confirm("Review the task worktree, Diff and checkpoint before resuming. Completed operations are retained; uncertain API reservations remain charged. Continue?")) return;
    await request("task.resume", {task_id:task.id, confirm_workspace:true, local_only:localOnly});
  };
  return <aside className="context-overlay" aria-label="Autonomous task">
    <div className="context-panel task-panel">
      <header className="context-panel-header"><div><span className="eyebrow">LOCAL-FIRST AUTONOMOUS CODING</span><h2>Task</h2></div><button className="panel-close" onClick={onClose}>Close</button></header>
      {error ? <div className="error-banner">{error}</div> : null}
      {notice ? <p role="status">{notice}</p> : null}
      {model ? <p className="task-model" role="status">{model}</p> : null}
      {config ? <section className="context-section">
        <label>Task strategy<select aria-label="Task strategy" value={config.strategy} disabled={running} onChange={e => setConfig({...config, strategy:e.target.value})}>
          <option value="local-first">Local-first</option><option value="local-only">Local-only</option><option value="api-only">API-only</option>
        </select></label>
        <p>Tasks edit an isolated Git worktree after approval. Source changes are preserved. No automatic commit, push or merge.</p>
        <textarea aria-label="Autonomous task goal" placeholder="Describe a coding task…" value={goal} onChange={e => setGoal(e.target.value)} />
        <label>Verification commands (one per line; empty = project discovery)<textarea aria-label="Verification commands" value={commands} onChange={e => setCommands(e.target.value)} /></label>
        <button disabled={busy || running || !goal.trim()} onClick={() => void request("task.start", {goal, config:currentConfig()})}>Start autonomous task</button>
        <details><summary>Models and budget</summary>
          <button onClick={onSettings}>Provider addresses and secure API key</button>
          {(["local", "api"] as const).map(route => <button key={route} disabled={busy} onClick={() => void request("task.connection.test", {route}).then(event => {if (event) setNotice(JSON.stringify(event.payload, null, 2));})}>Test {route} connection</button>)}
          {Object.entries(config.roles).map(([role, profile]) => <div className="task-role" key={role}>
            <label>{role}<select aria-label={role + " task profile"} value={profile.model_profile_id ?? ""} onChange={e => setConfig({...config, roles:{...config.roles, [role]:{...profile, model_profile_id:e.target.value}}})}><option value="">Legacy: {profile.model || "Not configured"}</option>{catalog.profiles.map(p => <option key={p.model_profile_id} value={p.model_profile_id}>{modelLabel(catalog,p)}</option>)}</select></label>
          </div>)}
          {Object.entries(config.budget).map(([key, value]) => <label key={key}>{key}<input aria-label={key} type="number" min="0" value={value ?? ""} placeholder="No cost cap" onChange={e => setConfig({...config, budget:{...config.budget, [key]:e.target.value === "" ? null : Number(e.target.value)}})} /></label>)}
          <p>Global usage is cumulative across tasks and restarts: API {String(globalUsage.api_calls ?? 0)}, reserved Tokens {String(globalUsage.reserved_tokens ?? 0)}.</p>
          <p>Token and cost caps use conservative reservations, output limits and timeouts. Provider tokenization/billing may differ. Unknown requests retain reservations. Prices are per million Tokens in your chosen billing currency.</p>
          <button disabled={busy || running} onClick={() => void request("task.settings.update", {config:currentConfig()}).then(event => {if (event) setNotice("Task defaults saved. Active task snapshots remain unchanged.");})}>Save task defaults</button>
          <details><summary>Advanced role limits, tool compatibility and prices</summary>
            <button onClick={() => setAdvanced(JSON.stringify(currentConfig(), null, 2))}>Load current configuration</button>
            <textarea aria-label="Advanced task configuration" className="task-json" value={advanced} onChange={e => setAdvanced(e.target.value)} />
            <button disabled={busy || running} onClick={() => {
              try {const next = JSON.parse(advanced) as Config; void request("task.settings.update", {config:next}).then(event => {if (event) {setConfig(event.payload?.config as Config); setCommands(next.verification_commands.join("\n"));}});} catch (cause) {setError(String(cause));}
            }}>Validate and save configuration</button>
          </details>
        </details>
      </section> : <p>Loading task configuration…</p>}
      {tasks.map(task => <section className="context-section" key={task.id}>
        <h3>{task.goal}</h3><strong data-task-status={task.status}>{task.status}</strong><p>{task.reason}</p>
        <p>Attempts {task.attempts} · Repairs {task.repairs} · Escalations {task.escalations} · {Math.round(task.elapsed_seconds)}s</p>
        <p>API {task.usage.api_calls} · Local {task.usage.local_calls} · Reserved Tokens {task.usage.reserved_tokens}</p>
        {task.config ? <p>API calls: {task.usage.api_calls} / {task.config.budget.api_calls} · API tokens reserved: {task.usage.reserved_tokens} / {task.config.budget.api_tokens} · Remaining {Math.max(0, Number(task.config.budget.api_tokens) - task.usage.reserved_tokens)}</p> : null}
        {task.calls?.length ? <details><summary>Model call journal</summary>{task.calls.map(call => <p key={call.id}>[{new Date(call.created_at * 1000).toLocaleTimeString()}] {call.role} · {call.usage.provider || call.route} / {call.model} · {call.status}</p>)}</details> : null}
        <p>API input {task.usage.input_tokens} · Output {task.usage.output_tokens} · Cached {task.usage.cached_tokens} {task.usage.estimated ? "(estimated)" : "(reported)"}</p>
        <p>Reserved cost {task.usage.reserved_cost.toFixed(6)} · Actual {task.usage.actual_cost_known ? task.usage.actual_cost.toFixed(6) : "unavailable"}</p>
        <details><summary>Usage precision</summary><p>{task.usage.precision}</p></details>
        {taskIsActive(task) ? <><button disabled={busy} onClick={() => void request("task.pause", {task_id:task.id})}>Pause task</button><button disabled={busy} onClick={() => void request("task.cancel", {task_id:task.id})}>Stop task</button></> : <>
          <button disabled={busy || running} onClick={() => void resume(task)}>Reopen / continue</button>
          <button disabled={busy || running} onClick={() => void resume(task, true)}>Continue local-only</button>
        </>}
        {task.status === "paused" ? <><button disabled={busy} onClick={() => {
          const raw = window.prompt('Explicit task budget update, e.g. {"api_calls":4,"api_tokens":40000}');
          if (!raw) return;
          try {void request("task.budget.add", {task_id:task.id, budget:JSON.parse(raw)});} catch (cause) {setError(String(cause));}
        }}>Add task budget</button><button disabled={busy || running} onClick={() => {
          if (window.confirm("Apply the model strategy, verification commands and budget currently shown above to this paused task? Provider addresses also refresh from Settings. Existing usage remains charged.")) void request("task.configure", {task_id:task.id, config:currentConfig()});
        }}>Apply configuration to paused task</button></> : null}
        <details><summary>Task plan and checkpoint</summary><ol>{task.plan.steps.map(step => <li key={step.id}>{step.description} — {step.state}</li>)}</ol><p>Worktree: {task.workspace || "Awaiting isolation approval"}<br />Branch: {task.branch}</p></details>
        {task.verification.map((test, i) => <details key={i}><summary>{test.ok ? "PASS" : "FAIL"} · {test.command || "Verification not configured"} · {test.category} · exit {test.exit_code ?? "—"} · {test.duration_ms}ms</summary><pre>{test.summary}</pre><p>Full log: {test.log_path}</p></details>)}
        {task.report.review ? <details><summary>Completion report and Git review</summary><p>{task.report.review}</p><p>{task.report.git_approval}</p><pre>{task.report.diff || "No tracked Diff"}</pre><button onClick={() => void window.localAgent.copyText(JSON.stringify(task, null, 2))}>Copy task report</button></details> : null}
        {task.status === "awaiting_approval" ? <button disabled={busy || running} onClick={() => void request("task.approve", {task_id:task.id})}>Accept verified report</button> : null}
      </section>)}
    </div>
  </aside>;
}
