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

type Tab =
  | "general"
  | "provider"
  | "agent"
  | "context"
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
  { id: "agent", label: "Agent" },
  { id: "context", label: "Context" },
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

  const changePermission = async (mode: PermissionMode) => {
    if (running) {
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const event = await window.localAgent.setPermission(mode);
      const next = event.payload?.mode;
      if (
        next === "read_only" ||
        next === "workspace" ||
        next === "full_access"
      ) {
        onPermissionChanged(next);
      }
      setMessage("Permission mode updated.");
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
          <div className="eyebrow">LOCAL CODING AGENT</div>
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

          {tab === "provider" ? (
            <div className="settings-section">
              <h2>Provider</h2>
              <label className="settings-field">
                <span>Provider</span>
                <select
                  value={settings.provider}
                  disabled={busy || running}
                  onChange={(event) =>
                    update(
                      "provider",
                      event.target.value as RuntimeSettings["provider"]
                    )
                  }
                >
                  <option value="ollama">Ollama</option>
                  <option value="openai_compatible">
                    OpenAI-compatible
                  </option>
                </select>
              </label>

              {settings.provider === "ollama" ? (
                <>
                  <label className="settings-field">
                    <span>Base URL</span>
                    <input
                      value={settings.ollama_base_url}
                      disabled={busy || running}
                      onChange={(event) =>
                        update("ollama_base_url", event.target.value)
                      }
                    />
                  </label>
                  <label className="settings-field">
                    <span>Preferred model</span>
                    <input
                      value={settings.ollama_model}
                      disabled={busy || running}
                      onChange={(event) =>
                        update("ollama_model", event.target.value)
                      }
                    />
                  </label>
                  <div className="settings-field-row">
                    <label className="settings-field">
                      <span>Context window</span>
                      <input
                        type="number"
                        min={1024}
                        max={262144}
                        value={settings.ollama_context_window}
                        disabled={busy || running}
                        onChange={(event) =>
                          update(
                            "ollama_context_window",
                            numberValue(
                              event.target.value,
                              settings.ollama_context_window
                            )
                          )
                        }
                      />
                    </label>
                    <label className="settings-field">
                      <span>Temperature</span>
                      <input
                        type="number"
                        step="0.1"
                        min={0}
                        max={2}
                        value={settings.ollama_temperature}
                        disabled={busy || running}
                        onChange={(event) =>
                          update(
                            "ollama_temperature",
                            numberValue(
                              event.target.value,
                              settings.ollama_temperature
                            )
                          )
                        }
                      />
                    </label>
                  </div>
                </>
              ) : (
                <>
                  <label className="settings-field">
                    <span>Base URL</span>
                    <input
                      value={settings.openai_base_url}
                      disabled={busy || running}
                      onChange={(event) =>
                        update("openai_base_url", event.target.value)
                      }
                    />
                  </label>
                  <label className="settings-field">
                    <span>Preferred model</span>
                    <input
                      value={settings.openai_model}
                      disabled={busy || running}
                      placeholder="Model ID from /models"
                      onChange={(event) =>
                        update("openai_model", event.target.value)
                      }
                    />
                  </label>
                  <div className="settings-field-row">
                    <label className="settings-field">
                      <span>Context window</span>
                      <input
                        type="number"
                        min={1024}
                        max={262144}
                        value={settings.openai_context_window}
                        disabled={busy || running}
                        onChange={(event) =>
                          update(
                            "openai_context_window",
                            numberValue(
                              event.target.value,
                              settings.openai_context_window
                            )
                          )
                        }
                      />
                    </label>
                    <label className="settings-field">
                      <span>Temperature</span>
                      <input
                        type="number"
                        step="0.1"
                        min={0}
                        max={2}
                        value={settings.openai_temperature}
                        disabled={busy || running}
                        onChange={(event) =>
                          update(
                            "openai_temperature",
                            numberValue(
                              event.target.value,
                              settings.openai_temperature
                            )
                          )
                        }
                      />
                    </label>
                  </div>
                  <label className="settings-field">
                    <span>API key</span>
                    <input
                      type="password"
                      value={apiKeyInput}
                      disabled={busy || running}
                      placeholder={
                        secret?.configured
                          ? "Configured — leave blank to keep current key"
                          : "Optional for local compatible servers"
                      }
                      onChange={(event) => {
                        setApiKeyInput(event.target.value);
                        setSecretAction(
                          event.target.value ? "set" : "keep"
                        );
                      }}
                    />
                    <small>{secretLabel(secret)}</small>
                  </label>
                  <div className="settings-inline-actions">
                    <button
                      type="button"
                      className="settings-secondary"
                      disabled={busy || running || !secret?.configured}
                      onClick={() => {
                        setApiKeyInput("");
                        setSecretAction("clear");
                        setMessage("API key will be cleared when settings are saved.");
                      }}
                    >
                      Clear API key
                    </button>
                  </div>
                </>
              )}
            </div>
          ) : null}

          {tab === "agent" ? (
            <div className="settings-section">
              <h2>Agent</h2>
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
              <h2>Safety</h2>
              <label className="settings-field">
                <span>Permission mode</span>
                <select
                  value={permissionMode}
                  disabled={busy || running}
                  onChange={(event) =>
                    void changePermission(
                      event.target.value as PermissionMode
                    )
                  }
                >
                  <option value="read_only">Read Only</option>
                  <option value="workspace">Workspace</option>
                  <option value="full_access">Full Access</option>
                </select>
              </label>
              <div className="settings-safety-note">
                <strong>Hard boundary</strong>
                <p>
                  Prompt Rules cannot bypass permission checks, workspace
                  boundaries or approval requirements. Risky publishing and
                  destructive operations remain approval-gated.
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
          disabled={busy || running}
          onClick={() => void save()}
        >
          {busy ? "Applying…" : "Save settings"}
        </button>
      </footer>
    </section>
  );
}
