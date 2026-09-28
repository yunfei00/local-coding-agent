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

type ThreadRecord = {
  id: string;
  title: string;
  created_at: string;
  updated_at: string;
};

type ChatItem = {
  id: string;
  role: "user" | "agent" | "system";
  text: string;
};

const initialStatus: Status = { state: "starting" };

function readThread(event: AgentEnvelope): ThreadRecord | null {
  const value = event.payload?.thread;
  if (!value || typeof value !== "object") {
    return null;
  }
  return value as ThreadRecord;
}

function App() {
  const [status, setStatus] = useState<Status>(initialStatus);
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
      if (event.type === "thread.created") {
        const thread = readThread(event);
        if (thread) {
          setThreads((current) => [thread, ...current.filter((item) => item.id !== thread.id)]);
          setActiveThread(thread);
          setItems([]);
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

      if (
        (event.type === "turn.completed" || event.type === "turn.cancelled") &&
        event.turn_id
      ) {
        setRunningTurnId((current) => (current === event.turn_id ? null : current));
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

      if (event.type === "error") {
        setUiError(String(event.payload?.message ?? "Agent error"));
      }
    });
  }, []);

  useEffect(() => {
    if (status.state !== "ready") {
      return;
    }

    void window.localAgent
      .listThreads()
      .then((event) => {
        const value = event.payload?.threads;
        if (Array.isArray(value)) {
          const loaded = value as ThreadRecord[];
          setThreads(loaded);
          setActiveThread((current) => current ?? loaded[0] ?? null);
        }
      })
      .catch((error) => setUiError(String(error)));
  }, [status.state]);

  const detail = useMemo(() => {
    if (status.state === "ready") {
      return [status.host + ":" + status.port, status.version, status.protocol].join(" · ");
    }
    return status.error ?? "Waiting for the local Agent process…";
  }, [status]);

  const createThread = async () => {
    setUiError(null);
    try {
      await window.localAgent.createThread();
    } catch (error) {
      setUiError(String(error));
    }
  };

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    const prompt = input.trim();
    if (!activeThread || !prompt || runningTurnId) {
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
      const started = await window.localAgent.startTurn(activeThread.id, prompt);
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
          className="new-thread"
          disabled={status.state !== "ready"}
          onClick={() => void createThread()}
        >
          + New thread
        </button>

        <div className="section-label">PROJECTS</div>
        <div className="empty-list">Workspace arrives in Phase 3</div>

        <div className="section-label">THREADS</div>
        <div className="thread-list">
          {threads.length === 0 ? (
            <div className="empty-list">No threads yet</div>
          ) : (
            threads.map((thread) => (
              <button
                key={thread.id}
                className={"thread-item " + (activeThread?.id === thread.id ? "active" : "")}
                onClick={() => {
                  setActiveThread(thread);
                  setItems([]);
                }}
              >
                {thread.title}
              </button>
            ))
          )}
        </div>

        <div className="sidebar-footer">
          <div className={"status-dot status-" + status.state} />
          <div>
            <div className="status-title">{formatAgentStatus(status.state)}</div>
            <div className="status-detail">{detail}</div>
          </div>
        </div>
      </aside>

      <main className="workspace">
        <header className="topbar">
          <div>
            <strong>{activeThread?.title ?? "Phase 1"}</strong>
            <span> · Thread / Turn protocol</span>
          </div>
          <span className="platform">{window.localAgent.platform}</span>
        </header>

        <section className="conversation">
          {items.length === 0 ? (
            <div className="welcome-card">
              <div className="eyebrow">PHASE 1</div>
              <h1>Thread / Turn transport is live.</h1>
              <p>
                Create a thread and send a prompt. The Python Agent Server will stream a simulated
                response over the authenticated local WebSocket. Ollama replaces the simulator in
                Phase 2.
              </p>
              <div className="milestones">
                <span>WebSocket ✓</span>
                <span>Thread ✓</span>
                <span>Turn ✓</span>
                <span>Streaming ✓</span>
                <span>Stop ✓</span>
              </div>
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
            disabled={!activeThread || status.state !== "ready"}
            placeholder={
              activeThread
                ? "Send a Phase 1 test prompt…"
                : "Create a thread to start testing the protocol."
            }
          />
          <div className="composer-row">
            <span>Model: simulator · Permission: protocol only</span>
            {runningTurnId ? (
              <button type="button" className="stop-button" onClick={() => void stop()}>
                Stop
              </button>
            ) : (
              <button
                type="submit"
                disabled={!activeThread || !input.trim() || status.state !== "ready"}
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
