import { FormEvent, useEffect, useMemo, useState } from "react";

import { AgentState, formatAgentStatus } from "./lib/status";

type Status = {
  state: AgentState;
  host?: string;
  port?: number;
  version?: string;
  protocol?: string;
  error?: string;
};

type ModelInfo = {
  name: string;
  size?: number | null;
  family?: string | null;
  parameter_size?: string | null;
  quantization_level?: string | null;
};

type ProviderStatus = {
  provider: string;
  online: boolean;
  base_url: string;
  models: ModelInfo[];
  default_model?: string | null;
  preferred_model?: string | null;
  context_window: number;
  error?: { code?: string; message?: string } | null;
};

type WorkspaceInfo = {
  path: string;
  name: string;
  tools: string[];
};

type ThreadRecord = {
  id: string;
  title: string;
  active_model?: string | null;
  created_at: string;
  updated_at: string;
};

type ChatItem = {
  id: string;
  role: "user" | "agent" | "system" | "tool";
  text: string;
};

type StoredMessage = {
  role: "user" | "assistant";
  content: string;
};

const initialStatus: Status = { state: "starting" };

function readThread(event: AgentEnvelope): ThreadRecord | null {
  const value = event.payload?.thread;
  if (!value || typeof value !== "object") {
    return null;
  }
  return value as ThreadRecord;
}

function readProvider(event: AgentEnvelope): ProviderStatus | null {
  const payload = event.payload;
  if (!payload || typeof payload.provider !== "string") {
    return null;
  }
  return payload as unknown as ProviderStatus;
}

function readWorkspace(event: AgentEnvelope): WorkspaceInfo | null {
  const payload = event.payload;
  if (!payload || typeof payload.path !== "string" || !payload.path) {
    return null;
  }
  return {
    path: payload.path,
    name: typeof payload.name === "string" ? payload.name : payload.path,
    tools: Array.isArray(payload.tools) ? payload.tools.map(String) : []
  };
}

function stringifyArguments(value: unknown): string {
  try {
    const text = JSON.stringify(value ?? {}, null, 0);
    return text.length > 500 ? text.slice(0, 500) + "…" : text;
  } catch {
    return String(value);
  }
}

function App() {
  const [status, setStatus] = useState<Status>(initialStatus);
  const [provider, setProvider] = useState<ProviderStatus | null>(null);
  const [workspace, setWorkspace] = useState<WorkspaceInfo | null>(null);
  const [selectedModel, setSelectedModel] = useState("");
  const [threads, setThreads] = useState<ThreadRecord[]>([]);
  const [activeThread, setActiveThread] = useState<ThreadRecord | null>(null);
  const [items, setItems] = useState<ChatItem[]>([]);
  const [input, setInput] = useState("");
  const [runningTurnId, setRunningTurnId] = useState<string | null>(null);
  const [uiError, setUiError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;

    const refresh = async () => {
      try {
        const next = await window.localAgent.getAgentStatus();
        if (active) {
          setStatus(next);
        }
      } catch (error) {
        if (active) {
          setStatus({ state: "error", error: String(error) });
        }
      }
    };

    void refresh();
    const timer = window.setInterval(() => void refresh(), 1000);
    return () => {
      active = false;
      window.clearInterval(timer);
    };
  }, []);

  useEffect(() => {
    return window.localAgent.onAgentEvent((event) => {
      if (event.type === "project.opened") {
        const nextWorkspace = readWorkspace(event);
        if (nextWorkspace) {
          setWorkspace(nextWorkspace);
          setThreads([]);
          setActiveThread(null);
          setItems([]);
        }
        return;
      }

      if (event.type === "thread.created") {
        const thread = readThread(event);
        if (thread) {
          setThreads((current) => [
            thread,
            ...current.filter((item) => item.id !== thread.id)
          ]);
          setActiveThread(thread);
          setSelectedModel(thread.active_model ?? "");
          setItems([]);
        }
        return;
      }

      if (event.type === "model.selected") {
        const thread = readThread(event);
        if (thread) {
          setThreads((current) =>
            current.map((item) => (item.id === thread.id ? thread : item))
          );
          setActiveThread((current) =>
            current?.id === thread.id ? thread : current
          );
          setSelectedModel(thread.active_model ?? "");
        }
        return;
      }

      if (event.type === "turn.started" && event.turn_id) {
        setRunningTurnId(event.turn_id);
        return;
      }

      if (event.type === "turn.delta" && event.turn_id) {
        const delta = String(event.payload?.delta ?? "");
        setItems((current) => {
          const id = "agent:" + event.turn_id;
          const existing = current.find((item) => item.id === id);
          if (existing) {
            return current.map((item) =>
              item.id === id ? { ...item, text: item.text + delta } : item
            );
          }
          return [...current, { id, role: "agent", text: delta }];
        });
        return;
      }

      if (event.type === "tool.requested" && event.turn_id) {
        const callId = String(event.payload?.tool_call_id ?? "");
        const name = String(event.payload?.name ?? "tool");
        const args = stringifyArguments(event.payload?.arguments);
        setItems((current) => [
          ...current,
          {
            id: "tool:" + callId,
            role: "tool",
            text: "▶ " + name + "\n" + args
          }
        ]);
        return;
      }

      if (event.type === "tool.output") {
        const callId = String(event.payload?.tool_call_id ?? "");
        const output = String(event.payload?.output ?? "");
        setItems((current) =>
          current.map((item) => {
            if (item.id !== "tool:" + callId) {
              return item;
            }
            const next = item.text + "\n" + output;
            return { ...item, text: next.length > 12000 ? next.slice(-12000) : next };
          })
        );
        return;
      }

      if (event.type === "tool.completed") {
        const callId = String(event.payload?.tool_call_id ?? "");
        const result = event.payload?.result;
        const summary =
          result && typeof result === "object" && "summary" in result
            ? String((result as { summary?: unknown }).summary ?? "")
            : "";
        const ok =
          result && typeof result === "object" && "ok" in result
            ? Boolean((result as { ok?: unknown }).ok)
            : false;

        setItems((current) =>
          current.map((item) =>
            item.id === "tool:" + callId
              ? {
                  ...item,
                  text: item.text + "\n" + (ok ? "✓ " : "✗ ") + summary
                }
              : item
          )
        );
        return;
      }

      if (event.type === "file.changed" && event.turn_id) {
        const path = String(event.payload?.path ?? "");
        setItems((current) => [
          ...current,
          {
            id: "changed:" + event.turn_id + ":" + path + ":" + Date.now(),
            role: "system",
            text: "Changed file: " + path
          }
        ]);
        return;
      }

      if (
        (event.type === "turn.completed" || event.type === "turn.cancelled") &&
        event.turn_id
      ) {
        setRunningTurnId((current) =>
          current === event.turn_id ? null : current
        );
        if (event.type === "turn.cancelled") {
          setItems((current) => [
            ...current,
            {
              id: "system:" + event.turn_id,
              role: "system",
              text: "Turn cancelled."
            }
          ]);
        }
        return;
      }

      if (event.type === "turn.failed" && event.turn_id) {
        const message = String(
          event.payload?.message ?? "Agent turn failed."
        );
        setRunningTurnId((current) =>
          current === event.turn_id ? null : current
        );
        setUiError(message);
        setItems((current) => [
          ...current,
          {
            id: "system:" + event.turn_id,
            role: "system",
            text: "Turn failed: " + message
          }
        ]);
        return;
      }

      if (event.type === "error") {
        setUiError(String(event.payload?.message ?? "Agent error"));
      }
    });
  }, []);

  useEffect(() => {
    if (status.state !== "ready") {
      return;
    }

    const load = async () => {
      try {
        const [projectEvent, threadEvent, modelEvent] = await Promise.all([
          window.localAgent.getProject(),
          window.localAgent.listThreads(),
          window.localAgent.listModels()
        ]);

        const loadedWorkspace = readWorkspace(projectEvent);
        if (loadedWorkspace) {
          setWorkspace(loadedWorkspace);
        }

        const threadValue = threadEvent.payload?.threads;
        if (Array.isArray(threadValue)) {
          const loaded = threadValue as ThreadRecord[];
          setThreads(loaded);
          if (loaded[0]) {
            setActiveThread((current) => current ?? loaded[0]);
          }
        }

        const providerStatus = readProvider(modelEvent);
        if (providerStatus) {
          setProvider(providerStatus);
          const modelNames = providerStatus.models.map((item) => item.name);
          setSelectedModel((current) => {
            if (current && modelNames.includes(current)) {
              return current;
            }
            return providerStatus.default_model ?? modelNames[0] ?? "";
          });
        }
      } catch (error) {
        setUiError(String(error));
      }
    };

    void load();
  }, [status.state]);

  const detail = useMemo(() => {
    if (status.state === "ready") {
      return [
        status.host + ":" + status.port,
        status.version,
        status.protocol
      ].join(" · ");
    }
    return status.error ?? "Waiting for the local Agent process…";
  }, [status]);

  const contextLabel = useMemo(() => {
    if (!provider?.context_window) {
      return "";
    }
    return Math.round(provider.context_window / 1024) + "K";
  }, [provider]);

  const providerReady = Boolean(provider?.online && selectedModel);

  const openProject = async () => {
    if (runningTurnId) {
      return;
    }
    setUiError(null);
    try {
      const result = await window.localAgent.openProject();
      if (result.canceled || !result.event) {
        return;
      }
      const next = readWorkspace(result.event);
      if (next) {
        setWorkspace(next);
        setThreads([]);
        setActiveThread(null);
        setItems([]);
      }
    } catch (error) {
      setUiError(String(error));
    }
  };

  const refreshModels = async () => {
    setUiError(null);
    try {
      const event = await window.localAgent.listModels();
      const next = readProvider(event);
      if (!next) {
        return;
      }
      setProvider(next);
      const names = next.models.map((item) => item.name);
      setSelectedModel((current) => {
        if (current && names.includes(current)) {
          return current;
        }
        return next.default_model ?? names[0] ?? "";
      });
    } catch (error) {
      setUiError(String(error));
    }
  };

  const createThread = async () => {
    setUiError(null);
    try {
      await window.localAgent.createThread(selectedModel || undefined);
    } catch (error) {
      setUiError(String(error));
    }
  };

  const loadThread = async (thread: ThreadRecord) => {
    if (runningTurnId) {
      return;
    }

    setUiError(null);
    try {
      const event = await window.localAgent.getThread(thread.id);
      const loadedThread = readThread(event) ?? thread;
      const rawMessages = event.payload?.messages;
      const messages = Array.isArray(rawMessages)
        ? (rawMessages as StoredMessage[])
        : [];

      setActiveThread(loadedThread);
      setSelectedModel(
        loadedThread.active_model ?? provider?.default_model ?? ""
      );
      setItems(
        messages.map((message, index) => ({
          id: "history:" + loadedThread.id + ":" + index,
          role: message.role === "assistant" ? "agent" : "user",
          text: message.content
        }))
      );
    } catch (error) {
      setUiError(String(error));
    }
  };

  const changeModel = async (model: string) => {
    setSelectedModel(model);
    setUiError(null);
    if (!activeThread) {
      return;
    }
    try {
      await window.localAgent.selectModel(activeThread.id, model);
    } catch (error) {
      setUiError(String(error));
    }
  };

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    const prompt = input.trim();
    if (
      !workspace ||
      !activeThread ||
      !prompt ||
      runningTurnId ||
      !providerReady
    ) {
      return;
    }

    setUiError(null);
    setInput("");
    setItems((current) => [
      ...current,
      {
        id: "user:" + Date.now(),
        role: "user",
        text: prompt
      }
    ]);

    try {
      const started = await window.localAgent.startTurn(
        activeThread.id,
        prompt
      );
      if (started.turn_id) {
        setRunningTurnId(started.turn_id);
      }
    } catch (error) {
      setUiError(String(error));
      setRunningTurnId(null);
    }
  };

  const stop = async () => {
    if (!runningTurnId) {
      return;
    }
    try {
      await window.localAgent.cancelTurn(runningTurnId);
    } catch (error) {
      setUiError(String(error));
    }
  };

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand">Local Coding Agent</div>

        <button
          className="open-project"
          disabled={status.state !== "ready" || Boolean(runningTurnId)}
          onClick={() => void openProject()}
        >
          Open project
        </button>

        <button
          className="new-thread"
          disabled={status.state !== "ready" || !providerReady || !workspace}
          onClick={() => void createThread()}
        >
          + New thread
        </button>

        <div className="section-label">PROJECT</div>
        {workspace ? (
          <div className="workspace-card" title={workspace.path}>
            <strong>{workspace.name}</strong>
            <span>{workspace.path}</span>
            <small>{workspace.tools.length} local tools</small>
          </div>
        ) : (
          <div className="empty-list">No project opened</div>
        )}

        <div className="section-label">THREADS</div>
        <div className="thread-list">
          {threads.length === 0 ? (
            <div className="empty-list">No threads yet</div>
          ) : (
            threads.map((thread) => (
              <button
                key={thread.id}
                className={
                  "thread-item " +
                  (activeThread?.id === thread.id ? "active" : "")
                }
                onClick={() => void loadThread(thread)}
              >
                <span>{thread.title}</span>
                <small>{thread.active_model ?? "no model"}</small>
              </button>
            ))
          )}
        </div>

        <div className="sidebar-footer">
          <div className={"status-dot status-" + status.state} />
          <div>
            <div className="status-title">
              {formatAgentStatus(status.state)}
            </div>
            <div className="status-detail">{detail}</div>
          </div>
        </div>
      </aside>

      <main className="workspace">
        <header className="topbar">
          <div>
            <strong>{activeThread?.title ?? "Phase 3"}</strong>
            <span> · Tool System v1</span>
          </div>
          <div className="topbar-actions">
            <button
              className={
                "provider-pill " +
                (provider?.online ? "provider-online" : "provider-offline")
              }
              onClick={() => void refreshModels()}
              title="Refresh Ollama status and local models"
            >
              Ollama {provider?.online ? "Online" : "Offline"}
            </button>
            <span className="platform">{window.localAgent.platform}</span>
          </div>
        </header>

        <section className="conversation">
          {items.length === 0 ? (
            <div className="welcome-card">
              <div className="eyebrow">PHASE 3</div>
              <h1>Local project tools are live.</h1>
              <p>
                Open a project, create a thread, then ask the Agent to inspect,
                test or modify the code. File access is confined to the selected
                workspace and destructive shell commands remain blocked.
              </p>
              <div className="milestones">
                <span>Workspace guard ✓</span>
                <span>Files ✓</span>
                <span>Search ✓</span>
                <span>Shell ✓</span>
                <span>Git ✓</span>
              </div>
              {!provider?.online ? (
                <div className="provider-warning">
                  {provider?.error?.message ??
                    "Ollama is not available. Start Ollama and refresh."}
                </div>
              ) : null}
            </div>
          ) : (
            <div className="message-list">
              {items.map((item) => (
                <div key={item.id} className={"message " + item.role}>
                  <div className="message-role">{item.role}</div>
                  <div>{item.text}</div>
                </div>
              ))}
            </div>
          )}
        </section>

        <form className="composer" onSubmit={submit}>
          {uiError ? <div className="error-banner">{uiError}</div> : null}
          <textarea
            value={input}
            onChange={(event) => setInput(event.target.value)}
            disabled={
              !workspace ||
              !activeThread ||
              status.state !== "ready" ||
              !providerReady
            }
            placeholder={
              !workspace
                ? "Open a project first."
                : !provider?.online
                  ? "Ollama is offline."
                  : activeThread
                    ? "Ask the Agent to inspect, test or modify this project…"
                    : "Create a thread to start working on the project."
            }
          />
          <div className="composer-row">
            <div className="model-controls">
              <select
                className="model-select"
                value={selectedModel}
                disabled={
                  !provider?.online ||
                  runningTurnId !== null ||
                  provider.models.length === 0
                }
                onChange={(event) => void changeModel(event.target.value)}
              >
                {provider?.models.length ? (
                  provider.models.map((model) => (
                    <option key={model.name} value={model.name}>
                      {model.name}
                    </option>
                  ))
                ) : (
                  <option value="">No local models</option>
                )}
              </select>
              <span>
                {contextLabel ? "Context " + contextLabel + " · " : ""}
                Permission: Workspace guarded
              </span>
            </div>
            {runningTurnId ? (
              <button
                type="button"
                className="stop-button"
                onClick={() => void stop()}
              >
                Stop
              </button>
            ) : (
              <button
                type="submit"
                disabled={
                  !workspace ||
                  !activeThread ||
                  !input.trim() ||
                  status.state !== "ready" ||
                  !providerReady
                }
              >
                Send
              </button>
            )}
          </div>
        </form>
      </main>
    </div>
  );
}

export default App;
