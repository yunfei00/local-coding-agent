import { useEffect, useMemo, useState } from "react";

type PinnedFile = {
  path: string;
  status: string;
  size?: number | null;
  truncated?: boolean;
};

type RepositoryMapInfo = {
  revision?: number;
  file_count?: number;
  symbol_count?: number;
  languages?: Record<string, number>;
  truncated?: boolean;
  files?: string[];
};

type ContextPayload = {
  repository_map?: RepositoryMapInfo;
  pinned?: PinnedFile[];
};

function readContext(event: AgentEnvelope): ContextPayload {
  return (event.payload ?? {}) as ContextPayload;
}

export function ContextPanel({
  threadId,
  projectName,
  running,
  onClose
}: {
  threadId: string;
  projectName?: string;
  running: boolean;
  onClose: () => void;
}) {
  const [payload, setPayload] = useState<ContextPayload>({});
  const [pathValue, setPathValue] = useState("");
  const [filter, setFilter] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = async () => {
    setBusy(true);
    setError(null);
    try {
      const event = await window.localAgent.getContext(threadId);
      setPayload(readContext(event));
    } catch (nextError) {
      setError(String(nextError));
    } finally {
      setBusy(false);
    }
  };

  useEffect(() => {
    void load();
  }, [threadId]);

  const files = payload.repository_map?.files ?? [];
  const pinned = payload.pinned ?? [];
  const filteredFiles = useMemo(() => {
    const query = filter.trim().toLowerCase();
    if (!query) {
      return files.slice(0, 80);
    }
    return files
      .filter((path) => path.toLowerCase().includes(query))
      .slice(0, 80);
  }, [files, filter]);

  const pin = async (path: string) => {
    const value = path.trim();
    if (!value || busy || running) {
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const event = await window.localAgent.pinContext(threadId, value);
      setPayload(readContext(event));
      setPathValue("");
    } catch (nextError) {
      setError(String(nextError));
    } finally {
      setBusy(false);
    }
  };

  const unpin = async (path: string) => {
    if (busy || running) {
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const event = await window.localAgent.unpinContext(threadId, path);
      setPayload(readContext(event));
    } catch (nextError) {
      setError(String(nextError));
    } finally {
      setBusy(false);
    }
  };

  const refresh = async () => {
    if (busy || running) {
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const event = await window.localAgent.refreshContext(threadId);
      setPayload(readContext(event));
    } catch (nextError) {
      setError(String(nextError));
    } finally {
      setBusy(false);
    }
  };

  const repo = payload.repository_map ?? {};
  const languages = Object.entries(repo.languages ?? {}).sort(
    (a, b) => b[1] - a[1]
  );

  return (
    <div className="context-overlay" role="dialog" aria-modal="true">
      <div className="context-panel">
        <header className="context-panel-header">
          <div>
            <span className="eyebrow">EXPLICIT CONTEXT</span>
            <h2>{projectName ?? "Workspace"} context</h2>
            <p>
              Pinned files persist for this thread. Use <code>@path/file.ext</code>
              in a message for one-turn context.
            </p>
          </div>
          <button type="button" className="panel-close" onClick={onClose}>
            Close
          </button>
        </header>

        {error ? <div className="error-banner">{error}</div> : null}

        <section className="context-repo-summary">
          <div>
            <span>Indexed files</span>
            <strong>{repo.file_count ?? 0}</strong>
          </div>
          <div>
            <span>Symbols</span>
            <strong>{repo.symbol_count ?? 0}</strong>
          </div>
          <div>
            <span>Revision</span>
            <strong>{repo.revision ?? 0}</strong>
          </div>
          <div>
            <span>Bounded</span>
            <strong>{repo.truncated ? "Truncated" : "Complete"}</strong>
          </div>
        </section>

        {languages.length ? (
          <div className="context-language-row">
            {languages.map(([name, count]) => (
              <span key={name}>
                {name} {count}
              </span>
            ))}
          </div>
        ) : null}

        <section className="context-section">
          <div className="context-section-heading">
            <div>
              <h3>Pinned files</h3>
              <p>Loaded before ordinary chat history on every turn.</p>
            </div>
            <button
              type="button"
              className="settings-secondary"
              disabled={busy || running}
              onClick={() => void refresh()}
            >
              {busy ? "Working…" : "Refresh repo map"}
            </button>
          </div>

          <div className="context-pin-input">
            <input
              value={pathValue}
              disabled={busy || running}
              placeholder="src/app.ts"
              list="repository-context-files"
              onChange={(event) => setPathValue(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === "Enter") {
                  event.preventDefault();
                  void pin(pathValue);
                }
              }}
            />
            <button
              type="button"
              disabled={busy || running || !pathValue.trim()}
              onClick={() => void pin(pathValue)}
            >
              Pin
            </button>
          </div>
          <datalist id="repository-context-files">
            {files.slice(0, 500).map((path) => (
              <option key={path} value={path} />
            ))}
          </datalist>

          {pinned.length ? (
            <div className="context-pinned-list">
              {pinned.map((item) => (
                <div key={item.path} className="context-pinned-item">
                  <div>
                    <strong>{item.path}</strong>
                    <span className={"context-file-status status-" + item.status}>
                      {item.status}
                      {item.truncated ? " · truncated" : ""}
                    </span>
                  </div>
                  <button
                    type="button"
                    className="settings-secondary"
                    disabled={busy || running}
                    onClick={() => void unpin(item.path)}
                  >
                    Remove
                  </button>
                </div>
              ))}
            </div>
          ) : (
            <div className="context-empty">
              No pinned files for this thread.
            </div>
          )}
        </section>

        <section className="context-section context-repo-files">
          <div className="context-section-heading">
            <div>
              <h3>Repository map</h3>
              <p>
                Deterministic source/config index. Build/dependency trees are
                ignored; no embeddings or vector database are used.
              </p>
            </div>
          </div>
          <input
            className="context-filter"
            value={filter}
            placeholder="Filter indexed files…"
            onChange={(event) => setFilter(event.target.value)}
          />
          <div className="context-file-list">
            {filteredFiles.map((path) => (
              <button
                key={path}
                type="button"
                disabled={busy || running}
                onClick={() => void pin(path)}
                title={"Pin " + path}
              >
                <code>{path}</code>
                <span>＋ Pin</span>
              </button>
            ))}
          </div>
        </section>
      </div>
    </div>
  );
}
