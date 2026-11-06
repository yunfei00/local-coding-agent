import { MCPSettingsSection } from "./MCPSettingsSection";
import { ModelSettingsSection } from "./ModelSettingsSection";
import { useEffect, useMemo, useState } from "react";

type PermissionMode = "read_only" | "workspace" | "full_access";

type RuntimeSettings = {
  provider: "ollama" | "openai_compatible";
  ollama_base_url: string;
  ollama_model: string;
  ollama_context_window: number;
  ollama_temperature: number;
  openai_base_url: string;
  openai_model: string;
  openai_context_window: number;
  openai_temperature: number;
  context_reserved_output_tokens: number;
  max_model_steps: number;
  max_tool_calls: number;
  max_blocked_repeats: number;
  max_consecutive_tool_failures: number;
  model_retry_attempts: number;
  api_key_configured?: boolean;
};

type SecretStatus = {
  configured: boolean;
  stored: boolean;
  mode: "os_protected" | "session_only" | "environment" | "none";
};

type PromptRule = {
  scope: "global" | "project" | "thread";
  scope_id?: string | null;
  content: string;
  enabled: boolean;
  updated_at?: string;
};

type PromptRulesPayload = {
  global?: PromptRule | null;
  project?: PromptRule | null;
  thread?: PromptRule | null;
};

type UpdateCheckResult = {
  ok: boolean;
  checked_at: string;
  current_version: string;
  latest_version?: string;
  update_available: boolean;
  release_url?: string;
  error?: string;
  automatic: false;
  can_auto_download: false;
  can_auto_install: false;
};

type Tab =
  | "general"
  | "provider"
  | "models"
  | "agent"
  | "context"
  | "mcp"
  | "prompt_rules"
  | "safety";

type Props = {
  projectId?: string;
  threadId?: string;
  permissionMode: PermissionMode;
  running: boolean;
  onClose: () => void;
  onProviderChanged: (event: AgentEnvelope) => void;
  onPermissionChanged: (mode: PermissionMode) => void;
};

const tabs: Array<{ id: Tab; label: string }> = [
  { id: "general", label: "General" },
  { id: "provider", label: "Provider" },
  { id: "models", label: "Models & Routing" },
  { id: "agent", label: "Agent" },
  { id: "context", label: "Context" },
  { id: "mcp", label: "MCP" },
  { id: "prompt_rules", label: "Prompt Rules" },
  { id: "safety", label: "Safety" }
];

function numberValue(value: string, fallback: number): number {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : fallback;
}

function readSettings(event: AgentEnvelope): RuntimeSettings | null {
  const payload = event.payload;
  if (!payload || typeof payload.provider !== "string") {
    return null;
  }
  return payload as unknown as RuntimeSettings;
}

function readRules(event: AgentEnvelope): PromptRulesPayload {
  const payload = event.payload ?? {};
  return {
    global:
      payload.global && typeof payload.global === "object"
        ? (payload.global as PromptRule)
        : null,
    project:
      payload.project && typeof payload.project === "object"
        ? (payload.project as PromptRule)
        : null,
    thread:
      payload.thread && typeof payload.thread === "object"
        ? (payload.thread as PromptRule)
        : null
  };
}

function secretLabel(secret: SecretStatus | null): string {
  if (!secret?.configured) {
    return "Not configured";
  }
  if (secret.mode === "os_protected") {
    return "Stored with OS-protected encryption";
  }
  if (secret.mode === "environment") {
    return "Provided by environment";
  }
  return "Session only";
}

export function SettingsPanel({
  projectId,
  threadId,
  permissionMode,
  running,
  onClose,
  onProviderChanged,
  onPermissionChanged
}: Props) {
  const [tab, setTab] = useState<Tab>("general");
  const [settings, setSettings] = useState<RuntimeSettings | null>(null);
  const [secret, setSecret] = useState<SecretStatus | null>(null);
  const [apiKeyInput, setApiKeyInput] = useState("");
  const [secretAction, setSecretAction] =
    useState<"keep" | "set" | "clear">("keep");
  const [rules, setRules] = useState<PromptRulesPayload>({});
  const [ruleDrafts, setRuleDrafts] = useState<Record<string, string>>({
    global: "",
    project: "",
    thread: ""
  });
  const [ruleEnabled, setRuleEnabled] = useState<Record<string, boolean>>({
    global: true,
    project: true,
    thread: true
  });
  const [busy, setBusy] = useState(false);
  const [permissionScope,setPermissionScope]=useState("global");
  const [permissionTask,setPermissionTask]=useState("");
  const [authorization,setAuthorization]=useState<{global:string;projects:Record<string,string>;tasks:Record<string,string>}|null>(null);
  useEffect(()=>{if(window.localAgent.getPermission)void window.localAgent.getPermission().then(event=>{setAuthorization(event.payload?.authorization as typeof authorization);setPermissionTask(String(event.payload?.task_key||''));}).catch(()=>{});},[projectId,threadId]);
  const [updateBusy, setUpdateBusy] = useState(false);
  const [downloadedUpdate,setDownloadedUpdate]=useState<string|null>(null);
  const [updateResult, setUpdateResult] =
    useState<UpdateCheckResult | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const loadRules = async () => {
    try {
      const event = await window.localAgent.getPromptRules(threadId);
      const next = readRules(event);
      setRules(next);
      setRuleDrafts({
        global: next.global?.content ?? "",
        project: next.project?.content ?? "",
        thread: next.thread?.content ?? ""
      });
      setRuleEnabled({
        global: next.global?.enabled ?? true,
        project: next.project?.enabled ?? true,
        thread: next.thread?.enabled ?? true
      });
    } catch (nextError) {
      setError(String(nextError));
    }
  };

  useEffect(() => {
    let active = true;
    const load = async () => {
      setError(null);
      try {
        const result = await window.localAgent.getSettings();
        if (!active) {
          return;
        }
        const next = readSettings(result.event);
        if (next) {
          setSettings(next);
        }
        setSecret(result.secret);
      } catch (nextError) {
        if (active) {
          setError(String(nextError));
        }
      }
    };
    void load();
    return () => {
      active = false;
    };
  }, []);

  useEffect(() => {
    void loadRules();
  }, [projectId, threadId]);

  const activeContextWindow = useMemo(() => {
    if (!settings) {
      return 0;
    }
    return settings.provider === "ollama"
      ? settings.ollama_context_window
      : settings.openai_context_window;
  }, [settings]);

  const update = <K extends keyof RuntimeSettings>(
    key: K,
    value: RuntimeSettings[K]
  ) => {
    setSettings((current) =>
      current ? { ...current, [key]: value } : current
    );
    setMessage(null);
  };

  const checkUpdates = async () => {
    setUpdateBusy(true);
    setError(null);
    try {
      const result = await window.localAgent.checkForUpdates();
      setUpdateResult(result);
    } catch (nextError) {
      setUpdateResult({
        ok: false,
        checked_at: new Date().toISOString(),
        current_version: "unknown",
        update_available: false,
        error: String(nextError),
        automatic: false,
        can_auto_download: false,
        can_auto_install: false
      });
    } finally {
      setUpdateBusy(false);
    }
  };

  const openRelease = async () => {
    const url = updateResult?.release_url;
    if (!url) {
      return;
    }
    setError(null);
    try {
      await window.localAgent.openReleasePage(url);
    } catch (nextError) {
      setError(String(nextError));
    }
  };

  const save = async () => {
    if (!settings || running) {
      return;
    }
    setBusy(true);
    setError(null);
    setMessage(null);
    try {
      const payload: Record<string, unknown> = { ...settings };
      delete payload.api_key_configured;
      const result = await window.localAgent.applySettings(payload, {
        action: secretAction,
        value: secretAction === "set" ? apiKeyInput : undefined
      });
      const next = readSettings(result.event);
      if (next) {
        setSettings(next);
      }
      setSecret(result.secret);
      setApiKeyInput("");
      setSecretAction("keep");
      onProviderChanged(result.provider);
      setMessage("Settings saved and applied.");
    } catch (nextError) {
      setError(String(nextError));
    } finally {
      setBusy(false);
    }
  };

  const reset = async () => {
    if (running) {
      return;
    }
    setBusy(true);
    setError(null);
    setMessage(null);
    try {
      const result = await window.localAgent.resetSettings();
      const next = readSettings(result.event);
      if (next) {
        setSettings(next);
      }
      setSecret(result.secret);
      setApiKeyInput("");
      setSecretAction("keep");
      onProviderChanged(result.provider);
      setMessage("Runtime settings reset to defaults.");
    } catch (nextError) {
      setError(String(nextError));
    } finally {
      setBusy(false);
    }
  };

  const saveRule = async (
    scope: "global" | "project" | "thread"
  ) => {
    if (running) {
      return;
    }
    const content = ruleDrafts[scope].trim();
    if (!content) {
      setError("Prompt rule content cannot be empty. Use Reset to remove it.");
      return;
    }
    setBusy(true);
    setError(null);
    setMessage(null);
    try {
      await window.localAgent.setPromptRule(
        scope,
        content,
        ruleEnabled[scope],
        projectId,
        threadId
      );
      await loadRules();
      setMessage(scope + " Prompt Rule saved.");
    } catch (nextError) {
      setError(String(nextError));
    } finally {
      setBusy(false);
    }
  };

  const resetRule = async (
    scope: "global" | "project" | "thread"
  ) => {
    if (running) {
      return;
    }
    setBusy(true);
    setError(null);
    setMessage(null);
    try {
      await window.localAgent.resetPromptRule(
        scope,
        projectId,
        threadId
      );
      await loadRules();
      setMessage(scope + " Prompt Rule reset.");
    } catch (nextError) {
      setError(String(nextError));
    } finally {
      setBusy(false);
    }
  };

  const changePermission = async (mode: PermissionMode | "inherit") => {
    setBusy(true);
    setError(null);
    try {
      const event = await window.localAgent.setPermission(mode,{scope:permissionScope,target:permissionScope==="project"?projectId:permissionScope==="task"?permissionTask:undefined});
      setAuthorization(event.payload?.authorization as typeof authorization);
      if(permissionScope==='task'&&event.payload?.canonical_target)setPermissionTask(String(event.payload.canonical_target));
      const next = event.payload?.mode;
      if (
        next === "read_only" ||
        next === "workspace" ||
        next === "full_access"
      ) {
        onPermissionChanged(next);
      }
      setMessage("权限已更新，新操作立即按有效授权检查。");
    } catch (nextError) {
      setError(String(nextError));
    } finally {
      setBusy(false);
    }
  };

  const renderRule = (
    scope: "global" | "project" | "thread",
    title: string,
    disabled: boolean
  ) => (
    <div className="settings-rule-card">
      <div className="settings-rule-header">
        <div>
          <strong>{title}</strong>
          <span>
            {rules[scope]
              ? rules[scope]?.enabled
                ? "Enabled"
                : "Disabled"
              : "Not configured"}
          </span>
        </div>
        <label className="settings-toggle">
          <input
            type="checkbox"
            checked={ruleEnabled[scope]}
            disabled={disabled || busy || running}
            onChange={(event) =>
              setRuleEnabled((current) => ({
                ...current,
                [scope]: event.target.checked
              }))
            }
          />
          Enabled
        </label>
      </div>
      <textarea
        value={ruleDrafts[scope]}
        disabled={disabled || busy || running}
        placeholder={
          disabled
            ? "Open the required project/thread first."
            : "Add instructions for this scope…"
        }
        onChange={(event) =>
          setRuleDrafts((current) => ({
            ...current,
            [scope]: event.target.value
          }))
        }
      />
      <div className="settings-inline-actions">
        <button
          type="button"
          disabled={disabled || busy || running}
          onClick={() => void saveRule(scope)}
        >
          Save rule
        </button>
        <button
          type="button"
          className="settings-secondary"
          disabled={disabled || busy || running || !rules[scope]}
          onClick={() => void resetRule(scope)}
        >
          Reset
        </button>
      </div>
    </div>
  );

  if (!settings) {
    return (
      <section className="settings-panel">
        <div className="settings-loading">
          {error ?? "Loading settings…"}
        </div>
      </section>
    );
  }

  return (
    <section className="settings-panel">
      <header className="settings-header">
        <div>
          <h1>Settings</h1>
        </div>
        <button type="button" onClick={onClose}>
          Close
        </button>
      </header>

      <div className="settings-body">
        <nav className="settings-nav">
          {tabs.map((item) => (
            <button
              key={item.id}
              type="button"
              className={tab === item.id ? "active" : ""}
              onClick={() => setTab(item.id)}
            >
              {item.label}
            </button>
          ))}
        </nav>

        <div className="settings-content">
          {error ? <div className="error-banner">{error}</div> : null}
          {message ? <div className="settings-success">{message}</div> : null}
          {running ? (
            <div className="settings-warning">
              Stop the active turn before changing runtime settings.
            </div>
          ) : null}

          {tab === "general" ? (
            <div className="settings-section">
              <h2>General</h2>
              <p>
                Settings are local to this desktop installation. Non-secret
                values persist in SQLite; provider credentials use protected
                desktop storage when available.
              </p>
              <div className="settings-summary-grid">
                <div>
                  <span>Provider</span>
                  <strong>{settings.provider}</strong>
                </div>
                <div>
                  <span>Context window</span>
                  <strong>{activeContextWindow.toLocaleString()}</strong>
                </div>
                <div>
                  <span>API key</span>
                  <strong>{secretLabel(secret)}</strong>
                </div>
                <div>
                  <span>Workspace</span>
                  <strong>{projectId ? "Open" : "None"}</strong>
                </div>
              </div>
              <div className="settings-update-card">
                <div>
                  <strong>更新与备份</strong>
                  <p>
                    从 GitHub Releases 手动检查和下载 Windows x64 更新。确认后暂停任务并备份，再安装重启；不在后台静默安装。
                  </p>
                </div>
                <div className="settings-update-actions">
                  <button
                    type="button"
                    className="settings-secondary"
                    disabled={updateBusy}
                    onClick={() => void checkUpdates()}
                  >
                    {updateBusy ? "处理中…" : "检查更新"}
                  </button>
                  {updateResult?.update_available &&
                  updateResult.release_url ? (
                    <button
                      type="button"
                      onClick={() => void openRelease()}
                    >
                      Open release page
                    </button>
                  ) : null}
                </div>
                <div className="settings-update-actions">
                  <button disabled={updateBusy} onClick={()=>{setUpdateBusy(true);setDownloadedUpdate(null);void window.localAgent.downloadUpdate().then(result=>{setDownloadedUpdate(result.version);setMessage('安装包 SHA256 已校验：'+result.sha256);}).catch(error=>setError(String(error))).finally(()=>setUpdateBusy(false));}}>下载并校验更新</button>
                  <button disabled={updateBusy||!downloadedUpdate} onClick={()=>{setUpdateBusy(true);void window.localAgent.installUpdate().catch(error=>setError(String(error))).finally(()=>setUpdateBusy(false));}}>备份并安装{downloadedUpdate?' v'+downloadedUpdate:''}</button>
                  <button disabled={updateBusy} onClick={()=>{setUpdateBusy(true);void window.localAgent.backupData().then(event=>setMessage('备份已保存：'+String(event.payload?.path))).catch(error=>setError(String(error))).finally(()=>setUpdateBusy(false));}}>备份应用数据</button>
                  <button onClick={()=>void window.localAgent.updateReceipt().then(record=>setMessage(record?.message||'没有待确认的更新记录')).catch(error=>setError(String(error)))}>检查上次更新</button>
                </div>
                {updateResult ? (
                  <div
                    className={
                      "settings-update-result " +
                      (updateResult.ok ? "ok" : "error")
                    }
                  >
                    {updateResult.ok ? (
                      updateResult.update_available ? (
                        <>
                          Update available: v
                          {updateResult.current_version} → v
                          {updateResult.latest_version}
                        </>
                      ) : (
                        <>
                          Up to date · v{updateResult.current_version}
                          {updateResult.latest_version
                            ? " · latest v" + updateResult.latest_version
                            : ""}
                        </>
                      )
                    ) : (
                      <>
                        Update check unavailable
                        {updateResult.error
                          ? " · " + updateResult.error
                          : ""}
                      </>
                    )}
                  </div>
                ) : null}
              </div>

              <div className="settings-bottom-actions">
                <button
                  type="button"
                  className="settings-secondary"
                  disabled={busy || running}
                  onClick={() => void reset()}
                >
                  Reset runtime settings
                </button>
              </div>
            </div>
          ) : null}

          {tab === "provider" ? <div className="settings-section"><h2>Provider Connections</h2><p>连接与模型统一由 Models &amp; Routing 管理。旧配置和凭据继续保留兼容。</p><button onClick={() => setTab("models")}>Manage model connections</button></div> : null}

          {tab === "agent" ? (
            <div className="settings-section">
              <h2>Agent</h2>
              <button disabled={busy || running} onClick={() => setSettings({...settings,
                max_model_steps:Math.max(settings.max_model_steps,100),
                max_tool_calls:Math.max(settings.max_tool_calls,512)})}>Use long task execution limits</button>
              <p>提高模型步骤与工具调用额度，保留重复操作、连续失败和 Provider 重试保护。点击 Save settings 后生效。</p>
              <div className="settings-field-row">
                <label className="settings-field">
                  <span>Max model steps</span>
                  <input
                    type="number"
                    min={1}
                    max={128}
                    value={settings.max_model_steps}
                    disabled={busy || running}
                    onChange={(event) =>
                      update(
                        "max_model_steps",
                        numberValue(event.target.value, settings.max_model_steps)
                      )
                    }
                  />
                </label>
                <label className="settings-field">
                  <span>Max tool calls</span>
                  <input
                    type="number"
                    min={1}
                    max={512}
                    value={settings.max_tool_calls}
                    disabled={busy || running}
                    onChange={(event) =>
                      update(
                        "max_tool_calls",
                        numberValue(event.target.value, settings.max_tool_calls)
                      )
                    }
                  />
                </label>
              </div>
              <div className="settings-field-row">
                <label className="settings-field">
                  <span>Blocked repeats</span>
                  <input
                    type="number"
                    min={1}
                    max={20}
                    value={settings.max_blocked_repeats}
                    disabled={busy || running}
                    onChange={(event) =>
                      update(
                        "max_blocked_repeats",
                        numberValue(
                          event.target.value,
                          settings.max_blocked_repeats
                        )
                      )
                    }
                  />
                </label>
                <label className="settings-field">
                  <span>Failure limit</span>
                  <input
                    type="number"
                    min={1}
                    max={50}
                    value={settings.max_consecutive_tool_failures}
                    disabled={busy || running}
                    onChange={(event) =>
                      update(
                        "max_consecutive_tool_failures",
                        numberValue(
                          event.target.value,
                          settings.max_consecutive_tool_failures
                        )
                      )
                    }
                  />
                </label>
              </div>
              <label className="settings-field">
                <span>Provider retry attempts</span>
                <input
                  type="number"
                  min={1}
                  max={5}
                  value={settings.model_retry_attempts}
                  disabled={busy || running}
                  onChange={(event) =>
                    update(
                      "model_retry_attempts",
                      numberValue(
                        event.target.value,
                        settings.model_retry_attempts
                      )
                    )
                  }
                />
              </label>
            </div>
          ) : null}

          {tab === "context" ? (
            <div className="settings-section">
              <h2>Context</h2>
              <p>
                The Agent keeps system rules and recent work inside the active
                provider context window, while reserving output capacity.
              </p>
              <label className="settings-field">
                <span>Reserved output tokens</span>
                <input
                  type="number"
                  min={256}
                  max={65536}
                  value={settings.context_reserved_output_tokens}
                  disabled={busy || running}
                  onChange={(event) =>
                    update(
                      "context_reserved_output_tokens",
                      numberValue(
                        event.target.value,
                        settings.context_reserved_output_tokens
                      )
                    )
                  }
                />
                <small>
                  Current provider window: {activeContextWindow.toLocaleString()}
                </small>
              </label>
            </div>
          ) : null}

          {tab === "models" ? <ModelSettingsSection threadId={threadId} running={running} /> : null}
          {tab === "mcp" ? (
            <MCPSettingsSection running={running} />
          ) : null}

          {tab === "prompt_rules" ? (
            <div className="settings-section">
              <h2>Prompt Rules</h2>
              <p>
                Effective order is Global → Project → Thread. Runtime
                permission and approval rules always remain authoritative.
              </p>
              {renderRule("global", "Global rules", false)}
              {renderRule("project", "Project rules", !projectId)}
              {renderRule("thread", "Thread rules", !threadId)}
            </div>
          ) : null}

          {tab === "safety" ? (
            <div className="settings-section">
              <h2>权限与安全</h2>
              <label className="settings-field"><span>授权范围</span><select value={permissionScope} onChange={e=>{const scope=e.target.value;setPermissionScope(scope);if(scope==='task')void window.localAgent.getPermission().then(event=>{setAuthorization(event.payload?.authorization as typeof authorization);setPermissionTask(String(event.payload?.task_key||''));}).catch(error=>setError(String(error)));}}>
                <option value="global">全局默认（新工程继承）</option><option value="project" disabled={!projectId}>当前项目覆盖</option><option value="task" disabled={!threadId}>当前任务临时覆盖</option>
              </select></label>
              {permissionScope==='task'?<label className="settings-field"><span>当前任务</span><code>{permissionTask||"尚无可授权任务，请先创建任务"}</code></label>:null}
              {permissionScope!=='global'?<button onClick={()=>void changePermission('inherit')}>撤销本范围覆盖，继承上级权限</button>:null}
              <label className="settings-field">
                <span>权限模式</span>
                <select
                  value={permissionScope==='global'?(authorization?.global||permissionMode):permissionScope==='project'?(authorization?.projects[projectId||'']||'inherit'):(authorization?.tasks[permissionTask]||'inherit')}
                  disabled={busy||(permissionScope==='task'&&!permissionTask)}
                  onChange={(event) =>
                    void changePermission(
                      event.target.value as PermissionMode | "inherit"
                    )
                  }
                >
                  {permissionScope!=='global'?<option value="inherit">继承上级权限</option>:null}
                  <option value="read_only">只读</option>
                  <option value="workspace">工作区</option>
                  <option value="full_access">完全访问</option>
                </select>
              </label>
              <div className="settings-safety-note">
                <strong>安全边界</strong>
                <p>
                  完全访问允许普通工具连续执行，首次启用确认一次；不取得管理员权限，不绕过 UAC、锁屏或系统保护。高风险、凭据外传、未知副作用重放和远程发布仍单独限制。可随时撤销，新操作立即生效。
                </p>
              </div>
            </div>
          ) : null}
        </div>
      </div>

      <footer className="settings-footer">
        <span>
          {secret?.mode === "session_only"
            ? "OS protected storage unavailable: API key is session-only."
            : "Secrets are never stored in SQLite."}
        </span>
        <button
          type="button"
          disabled={busy || running || tab === "models"}
          onClick={() => void save()}
        >
          {busy ? "Applying…" : "Save settings"}
        </button>
      </footer>
    </section>
  );
}
