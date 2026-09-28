import { useEffect, useMemo, useState } from "react";

import { AgentState, formatAgentStatus } from "./lib/status";

type Status = {
  state: AgentState;
  host?: string;
  port?: number;
  version?: string;
  protocol?: string;
  error?: string;
};

const initialStatus: Status = { state: "starting" };

function App() {
  const [status, setStatus] = useState<Status>(initialStatus);

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

  const detail = useMemo(() => {
    if (status.state === "ready") {
      return [status.host + ":" + status.port, status.version, status.protocol].join(" · ");
    }
    return status.error ?? "Waiting for the local Agent process…";
  }, [status]);

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand">Local Coding Agent</div>
        <button className="new-thread" disabled>
          + New thread
        </button>

        <div className="section-label">PROJECTS</div>
        <div className="empty-list">No project opened</div>

        <div className="section-label">THREADS</div>
        <div className="empty-list">Threads arrive in Phase 1</div>

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
            <strong>Phase 0</strong>
            <span> · Desktop + Agent bootstrap</span>
          </div>
          <span className="platform">{window.localAgent.platform}</span>
        </header>

        <section className="conversation">
          <div className="welcome-card">
            <div className="eyebrow">LOCAL FIRST</div>
            <h1>Your own coding agent starts here.</h1>
            <p>
              The Electron desktop is running and owns a private local Python Agent process.
              WebSocket threads, Ollama, tools and the Agent Loop are added in the next phases.
            </p>
            <div className="milestones">
              <span>Desktop ✓</span>
              <span>Agent process ✓</span>
              <span>Private localhost token ✓</span>
              <span>Health contract ✓</span>
            </div>
          </div>
        </section>

        <footer className="composer">
          <textarea
            disabled
            placeholder="Coding prompt input unlocks after the Thread / Turn protocol is implemented."
          />
          <div className="composer-row">
            <span>Model: coming in Phase 2</span>
            <button disabled>Send</button>
          </div>
        </footer>
      </main>
    </div>
  );
}

export default App;
