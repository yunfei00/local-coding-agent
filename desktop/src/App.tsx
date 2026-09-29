import {
  FormEvent,
  useCallback,
  useEffect,
  useMemo,
  useState
} from "react";

import { shouldSubmitComposer } from "./lib/composer";
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

type ProjectInfo = {
  id: string;
  path: string;
  name: string;
  tools: string[];
  thread_count: number;
  created_at?: string;
  updated_at?: string;
  active?: boolean;
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

type ProjectSessionPayload = {
  project: ProjectInfo;
  threads: ThreadRecord[];
  activeThread: ThreadRecord | null;
  messages: StoredMessage[];
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

function readProjectList(event: AgentEnvelope): ProjectInfo[] {
  const value = event.payload?.projects;
  return Array.isArray(value) ? (value as ProjectInfo[]) : [];
}

function readProjectSession(event: AgentEnvelope): ProjectSessionPayload | null {
  const project = event.payload?.project;
  if (!project || typeof project !== "object") {
    return null;
  }

  const rawThreads = event.payload?.threads;
  const activeThread = event.payload?.active_thread;
  const rawMessages = event.payload?.messages;

  return {
    project: project as ProjectInfo,
    threads: Array.isArray(rawThreads) ? (rawThreads as ThreadRecord[]) : [],
    activeThread:
      activeThread && typeof activeThread === "object"
        ? (activeThread as ThreadRecord)
        : null,
    messages: Array.isArray(rawMessages)
      ? (rawMessages as StoredMessage[])
      : []
  };
}

function historyItems(
  projectId: string,
  threadId: string,
  messages: StoredMessage[]
): ChatItem[] {
  return messages.map((message, index) => ({
    id: "history:" + projectId + ":" + threadId + ":" + index,
    role: message.role === "assistant" ? "agent" : "user",
    text: message.content
  }));
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
  const [projects, setProjects] = useState<ProjectInfo[]>([]);
  const [workspace, setWorkspace] = useState<ProjectInfo | null>(null);
  const [selectedModel, setSelectedModel] = useState("");
  const [threads, setThreads] = useState<ThreadRecord[]>([]);
  const [activeThread, setActiveThread] = useState<ThreadRecord | null>(null);
  const [items, setItems] = useState<ChatItem[]>([]);
  const [input, setInput] = useState("");
  const [runningTurnId, setRunningTurnId] = useState<string | null>(null);
  const [uiError, setUiError] = useState<string | null>(null);

  const applyProjectSession = useCallback((event: AgentEnvelope) => {
    const session = readProjectSession(event);
    if (!session) {
      return;
    }

    const activeProject = { ...session.project, active: true };
    setWorkspace(activeProject);
    setThreads(session.threads);
    setActiveThread(session.activeThread);
    setItems(
      session.activeThread
        ? historyItems(
            activeProject.id,
            session.activeThread.id,
            session.messages
          )
        : []
    );

    if (session.activeThread?.active_model) {
      setSelectedModel(session.activeThread.active_model);
    }

    setProjects((current) => {
      const next = current
        .filter((project) => project.id !== activeProject.id)
        .map((project) => ({ ...project, active: false }));
      return [activeProject, ...next];
    });
  }, []);

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
      if (
        event.type === "project.opened" ||
        event.type === "project.selected"
      ) {
        applyProjectSession(event);
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
          setProjects((current) =>
            current.map((project) =>
              project.active
                ? { ...project, thread_count: project.thread_count + 1 }
                : project
            )
          );
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
            return {
              ...item,
              text: next.length > 12000 ? next.slice(-12000) : next
            };
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

      if (event.type === "turn.status" && event.turn_id) {
        const message = String(event.payload?.message ?? "Agent is working…");
        const id = "status:" + event.turn_id;
        setItems((current) => {
          const existing = current.find((item) => item.id === id);
          if (existing) {
            return current.map((item) =>
              item.id === id ? { ...item, text: message } : item
            );
          }
          return [...current, { id, role: "system", text: message }];
        });
        return;
      }

      if (event.type === "turn.completed" && event.turn_id) {
        setRunningTurnId((current) =>
          current === event.turn_id ? null : current
        );

        const verification = event.payload?.verification;
        if (
          verification &&
          typeof verification === "object" &&
          "complete" in verification &&
          !(verification as { complete?: boolean }).complete
        ) {
          const missingValue = (verification as { missing?: unknown }).missing;
          const missing = Array.isArray(missingValue)
            ? missingValue.map(String)
            : [];
          setItems((current) => [
            ...current,
            {
              id: "verification:" + event.turn_id,
              role: "system",
              text:
                "Verification incomplete: " +
                (missing.length ? missing.join(", ") : "unknown checks")
            }
          ]);
        }
        return;
      }

      if (event.type === "turn.cancelled" && event.turn_id) {
        setRunningTurnId((current) =>
          current === event.turn_id ? null : current
        );
        setItems((current) => [
          ...current,
          {
            id: "system:" + event.turn_id,
            role: "system",
            text: "Turn cancelled."
          }
        ]);
        return;
      }

      if (event.type === "turn.failed" && event.turn_id) {
        const message = String(event.payload?.message ?? "Agent turn failed.");
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
  }, [applyProjectSession]);

  useEffect(() => {
    if (status.state !== "ready") {
      return;
    }

    const load = async () => {
      try {
        const [projectEvent, projectListEvent, modelEvent] =
          await Promise.all([
            window.localAgent.getProject(),
            window.localAgent.listProjects(),
            window.localAgent.listModels()
          ]);

        setProjects(readProjectList(projectListEvent));
        applyProjectSession(projectEvent);

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
  }, [status.state, applyProjectSession]);

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
      const result = await window.localAgent.openProject(
        selectedModel || undefined
      );
      if (result.canceled || !result.event) {
        return;
      }
      applyProjectSession(result.event);

      const listEvent = await window.localAgent.listProjects();
      setProjects(readProjectList(listEvent));
    } catch (error) {
      setUiError(String(error));
    }
  };

  const selectProject = async (project: ProjectInfo) => {
    if (runningTurnId || project.id === workspace?.id) {
      return;
    }

    setUiError(null);
    try {
      const event = await window.localAgent.selectProject(
        project.id,
        selectedModel || undefined
      );
      applyProjectSession(event);

      const listEvent = await window.localAgent.listProjects();
      setProjects(readProjectList(listEvent));
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
    if (runningTurnId || !workspace) {
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
      setItems(historyItems(workspace.id, loadedThread.id, messages));
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

        <div className="sidebar-actions">
          <button
            className="open-project"
            disabled={status.state !== "ready" || Boolean(runningTurnId)}
            onClick={() => void openProject()}
          >
            Open project
          </button>

          <button
            className="new-thread"
            disabled={
              status.state !== "ready" || !providerReady || !workspace
            }
            onClick={() => void createThread()}
          >
            + New thread
          </button>
        </div>

        <div className="sidebar-scroll">
          <div className="section-label">PROJECTS</div>
          <div className="project-list">
            {projects.length === 0 ? (
              <div className="empty-list">No projects opened</div>
            ) : (
              projects.map((project) => (
                <button
                  key={project.id}
                  className={
                    "project-item " +
                    (workspace?.id === project.id ? "active" : "")
                  }
                  disabled={Boolean(runningTurnId)}
                  title={project.path}
                  onClick={() => void selectProject(project)}
                >
                  <strong>{project.name}</strong>
                  <span>{project.path}</span>
                  <small>
                    {project.thread_count} thread
                    {project.thread_count === 1 ? "" : "s"}
                  </small>
                </button>
              ))
            )}
          </div>

          <div className="section-label">THREADS</div>
          <div className="thread-list">
            {threads.length === 0 ? (
              <div className="empty-list">
                {workspace ? "No threads yet" : "Select a project"}
              </div>
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
          <div className="topbar-title">
            <strong>{workspace?.name ?? "Phase 4"}</strong>
            <span>
              {activeThread ? " · " + activeThread.title : " · Full Agent Loop"}
            </span>
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
              <div className="eyebrow">PHASE 4</div>
              <h1>
                {workspace
                  ? "Project ready. Agent loop is active."
                  : "Open a local project to begin."}
              </h1>
              <p>
                {workspace
                  ? "Send a coding task and the Agent can inspect, execute, recover from failures, modify files and verify its work before finishing."
                  : "Each opened project stays in the left sidebar for this app session. Switching projects changes the active workspace without discarding the others."}
              </p>
              <div className="milestones">
                <span>Loop guard ✓</span>
                <span>Failure recovery ✓</span>
                <span>Context control ✓</span>
                <span>Verification ✓</span>
                <span>Stop ✓</span>
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
            onKeyDown={(event) => {
              if (
                shouldSubmitComposer({
                  key: event.key,
                  shiftKey: event.shiftKey,
                  isComposing: event.nativeEvent.isComposing
                })
              ) {
                event.preventDefault();
                event.currentTarget.form?.requestSubmit();
              }
            }}
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
                  : "Ask the Agent to inspect, test or modify this project…"
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
                Permission: Workspace guarded · Enter send · Shift+Enter newline
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
