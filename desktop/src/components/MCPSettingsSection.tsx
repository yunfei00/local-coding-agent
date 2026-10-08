import { useEffect, useMemo, useState } from "react";

type McpTransport = "stdio" | "streamable_http";

type McpTool = {
  name: string;
  remote_tool: string;
  read_only: boolean;
  risk?: string;
};

type McpServer = {
  id: string;
  name: string;
  transport: McpTransport;
  command?: string | null;
  args?: string[];
  url?: string | null;
  env?: Record<string, string>;
  secret_env_keys?: string[];
  enabled: boolean;
  trusted: boolean;
  timeout_seconds: number;
  secret_configured?: boolean;
  status?: {
    connected?: boolean;
    protocol_version?: string | null;
    server_name?: string | null;
    server_version?: string | null;
    error?: string | null;
  };
  tools?: McpTool[];
};

type SecretStatus = {
  configured: boolean;
  keys: string[];
  stored: boolean;
  mode: "os_protected" | "session_only" | "environment" | "none";
};

type Draft = {
  id?: string;
  name: string;
  transport: McpTransport;
  command: string;
  argsText: string;
  url: string;
  envText: string;
  secretKeysText: string;
  enabled: boolean;
  trusted: boolean;
  timeout_seconds: number;
};

const emptyDraft = (): Draft => ({
  name: "",
  transport: "stdio",
  command: "",
  argsText: "",
  url: "",
  envText: "{}",
  secretKeysText: "",
  enabled: true,
  trusted: false,
  timeout_seconds: 30
});

function readServers(event: AgentEnvelope): McpServer[] {
  const servers = event.payload?.servers;
  return Array.isArray(servers) ? (servers as McpServer[]) : [];
}

function toDraft(server: McpServer): Draft {
  return {
    id: server.id,
    name: server.name,
    transport: server.transport,
    command: server.command ?? "",
    argsText: (server.args ?? []).join("\n"),
    url: server.url ?? "",
    envText: JSON.stringify(server.env ?? {}, null, 2),
    secretKeysText: (server.secret_env_keys ?? []).join(", "),
    enabled: server.enabled,
    trusted: server.trusted,
    timeout_seconds: server.timeout_seconds ?? 30
  };
}

function parseObject(
  value: string,
  label: string
): Record<string, string> {
  const parsed = JSON.parse(value || "{}") as unknown;
  if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
    throw new Error(label + " must be a JSON object.");
  }
  return Object.fromEntries(
    Object.entries(parsed as Record<string, unknown>).map(([key, item]) => [
      key,
      String(item)
    ])
  );
}

function splitValues(value: string): string[] {
  return Array.from(
    new Set(
      value
        .split(/[\n,]/)
        .map((item) => item.trim())
        .filter(Boolean)
    )
  );
}

export function MCPSettingsSection({ running }: { running: boolean }) {
  const [servers, setServers] = useState<McpServer[]>([]);
  const [secrets, setSecrets] = useState<Record<string, SecretStatus>>({});
  const [draft, setDraft] = useState<Draft>(emptyDraft);
  const [secretInput, setSecretInput] = useState("");
  const [secretAction, setSecretAction] =
    useState<"keep" | "set" | "clear">("keep");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const selected = useMemo(
    () => servers.find((item) => item.id === draft.id) ?? null,
    [servers, draft.id]
  );

  const applyResult = (
    result: {
      event: AgentEnvelope;
      secrets?: Record<string, SecretStatus>;
    },
    preferredId?: string
  ) => {
    const next = readServers(result.event);
    setServers(next);
    if (result.secrets) {
      setSecrets(result.secrets);
    }
    const id = preferredId ?? draft.id;
    const selectedNext = next.find((item) => item.id === id);
    if (selectedNext) {
      setDraft(toDraft(selectedNext));
    }
  };

  const load = async () => {
    setBusy(true);
    setError(null);
    try {
      const result = await window.localAgent.listMcpServers();
      applyResult(result);
    } catch (nextError) {
      setError(String(nextError));
    } finally {
      setBusy(false);
    }
  };

  useEffect(() => {
    void load();
  }, []);

  const choose = (server: McpServer) => {
    setDraft(toDraft(server));
    setSecretInput("");
    setSecretAction("keep");
    setMessage(null);
    setError(null);
  };

  const createNew = () => {
    setDraft(emptyDraft());
    setSecretInput("");
    setSecretAction("keep");
    setMessage(null);
    setError(null);
  };

  const save = async () => {
    if (running || busy) {
      return;
    }
    setBusy(true);
    setError(null);
    setMessage(null);
    try {
      const env = parseObject(draft.envText, "Environment");
      let secretValues: Record<string, string> | undefined;
      if (secretAction === "set") {
        secretValues = parseObject(
          secretInput || "{}",
          "Secret environment"
        );
      }
      const secretKeys = Array.from(
        new Set([
          ...splitValues(draft.secretKeysText),
          ...Object.keys(secretValues ?? {})
        ])
      );
      const server = {
        ...(draft.id ? { id: draft.id } : {}),
        name: draft.name.trim(),
        transport: draft.transport,
        command:
          draft.transport === "stdio"
            ? draft.command.trim()
            : "",
        args:
          draft.transport === "stdio"
            ? draft.argsText
                .split("\n")
                .map((item) => item.trim())
                .filter(Boolean)
            : [],
        url:
          draft.transport === "streamable_http"
            ? draft.url.trim()
            : "",
        env,
        secret_env_keys: secretKeys,
        enabled: draft.enabled,
        trusted: draft.trusted,
        timeout_seconds: draft.timeout_seconds
      };
      const result = await window.localAgent.upsertMcpServer(
        server,
        {
          action: secretAction,
          values: secretValues
        }
      );
      applyResult(result);
      const saved = readServers(result.event).find(
        (item) => item.name === server.name
      );
      if (saved) {
        setDraft(toDraft(saved));
      }
      setSecretInput("");
      setSecretAction("keep");
      setMessage("MCP server saved and runtime refreshed.");
    } catch (nextError) {
      setError(String(nextError));
    } finally {
      setBusy(false);
    }
  };

  const remove = async () => {
    if (!draft.id || running || busy) {
      return;
    }
    setBusy(true);
    setError(null);
    setMessage(null);
    try {
      const result = await window.localAgent.deleteMcpServer(draft.id);
      applyResult(result);
      createNew();
      setMessage("MCP server removed.");
    } catch (nextError) {
      setError(String(nextError));
    } finally {
      setBusy(false);
    }
  };

  const refresh = async () => {
    if (running || busy) {
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const result = await window.localAgent.refreshMcpServers();
      applyResult(result);
      setMessage("MCP connections refreshed.");
    } catch (nextError) {
      setError(String(nextError));
    } finally {
      setBusy(false);
    }
  };

  const selectedSecret = draft.id ? secrets[draft.id] : undefined;

  return (
    <div className="settings-section mcp-settings">
      <div className="mcp-settings-heading">
        <div>
          <h2>MCP</h2>
          <p>
            Connect local stdio or Streamable HTTP MCP servers. Unknown or
            mutating MCP tools remain approval-gated.
          </p>
        </div>
        <div className="settings-inline-actions">
          <button
            type="button"
            className="settings-secondary"
            disabled={busy || running}
            onClick={() => void refresh()}
          >
            {busy ? "Working…" : "Refresh"}
          </button>
          <button
            type="button"
            disabled={busy || running}
            onClick={createNew}
          >
            New server
          </button>
        </div>
      </div>

      {error ? <div className="error-banner">{error}</div> : null}
      {message ? <div className="settings-success">{message}</div> : null}

      <div className="mcp-layout">
        <aside className="mcp-server-list">
          {servers.length === 0 ? (
            <div className="mcp-empty">No MCP servers configured.</div>
          ) : (
            servers.map((server) => (
              <button
                type="button"
                key={server.id}
                className={
                  "mcp-server-item" +
                  (server.id === draft.id ? " active" : "")
                }
                onClick={() => choose(server)}
              >
                <span
                  className={
                    "mcp-status-dot " +
                    (server.status?.connected ? "online" : "offline")
                  }
                />
                <span className="mcp-server-copy">
                  <strong>{server.name}</strong>
                  <small>
                    {server.transport === "stdio"
                      ? "stdio"
                      : "HTTP"}
                    {" · "}
                    {server.enabled ? "enabled" : "disabled"}
                    {" · "}
                    {(server.tools ?? []).length} tools
                  </small>
                </span>
              </button>
            ))
          )}
        </aside>

        <div className="mcp-editor">
          <div className="settings-field-row">
            <label className="settings-field">
              <span>Name</span>
              <input
                value={draft.name}
                disabled={busy || running}
                placeholder="filesystem"
                onChange={(event) =>
                  setDraft((current) => ({
                    ...current,
                    name: event.target.value
                  }))
                }
              />
            </label>
            <label className="settings-field">
              <span>Transport</span>
              <select
                value={draft.transport}
                disabled={busy || running}
                onChange={(event) =>
                  setDraft((current) => ({
                    ...current,
                    transport: event.target.value as McpTransport
                  }))
                }
              >
                <option value="stdio">stdio</option>
                <option value="streamable_http">
                  Streamable HTTP
                </option>
              </select>
            </label>
          </div>

          {draft.transport === "stdio" ? (
            <>
              <label className="settings-field">
                <span>Command</span>
                <input
                  value={draft.command}
                  disabled={busy || running}
                  placeholder=".venv\\Scripts\\python.exe / npx / uvx / executable"
                  onChange={(event) =>
                    setDraft((current) => ({
                      ...current,
                      command: event.target.value
                    }))
                  }
                />
                <small>
                  Python-based MCP servers run with exactly this interpreter.
                  Use an absolute virtual-environment Python path when the
                  server dependencies are installed in that environment.
                </small>
              </label>
              <label className="settings-field">
                <span>Arguments · one per line</span>
                <textarea
                  className="mcp-textarea"
                  value={draft.argsText}
                  disabled={busy || running}
                  placeholder={"-y\n@modelcontextprotocol/server-filesystem\nC:\\code"}
                  onChange={(event) =>
                    setDraft((current) => ({
                      ...current,
                      argsText: event.target.value
                    }))
                  }
                />
              </label>
            </>
          ) : (
            <label className="settings-field">
              <span>URL</span>
              <input
                value={draft.url}
                disabled={busy || running}
                placeholder="https://example.com/mcp"
                onChange={(event) =>
                  setDraft((current) => ({
                    ...current,
                    url: event.target.value
                  }))
                }
              />
            </label>
          )}

          <div className="settings-field-row">
            <label className="settings-field">
              <span>Timeout seconds</span>
              <input
                type="number"
                min={1}
                max={300}
                value={draft.timeout_seconds}
                disabled={busy || running}
                onChange={(event) =>
                  setDraft((current) => ({
                    ...current,
                    timeout_seconds:
                      Number(event.target.value) || 30
                  }))
                }
              />
            </label>
            <div className="mcp-switches">
              <label className="settings-toggle">
                <input
                  type="checkbox"
                  checked={draft.enabled}
                  disabled={busy || running}
                  onChange={(event) =>
                    setDraft((current) => ({
                      ...current,
                      enabled: event.target.checked
                    }))
                  }
                />
                Enabled
              </label>
              <label className="settings-toggle">
                <input
                  type="checkbox"
                  checked={draft.trusted}
                  disabled={busy || running}
                  onChange={(event) =>
                    setDraft((current) => ({
                      ...current,
                      trusted: event.target.checked
                    }))
                  }
                />
                Trusted server
              </label>
            </div>
          </div>

          <label className="settings-field">
            <span>
              {draft.transport === "stdio"
                ? "Non-secret environment · JSON"
                : "Non-secret HTTP headers · JSON"}
            </span>
            <textarea
              className="mcp-textarea"
              value={draft.envText}
              disabled={busy || running}
              onChange={(event) =>
                setDraft((current) => ({
                  ...current,
                  envText: event.target.value
                }))
              }
            />
            <small>
              {draft.transport === "stdio"
                ? "Environment references such as ${HOME} may be stored."
                : "Headers are sent with the Streamable HTTP client."}
              {" "}Credentials should use the protected secret section below.
            </small>
          </label>

          <label className="settings-field">
            <span>
              {draft.transport === "stdio"
                ? "Secret environment keys"
                : "Secret HTTP header keys"}
            </span>
            <input
              value={draft.secretKeysText}
              disabled={busy || running}
              placeholder="GITHUB_TOKEN, API_KEY"
              onChange={(event) =>
                setDraft((current) => ({
                  ...current,
                  secretKeysText: event.target.value
                }))
              }
            />
            <small>
              Only key names persist in SQLite. Values come from protected
              desktop storage or the process environment.
            </small>
          </label>

          <label className="settings-field">
            <span>
              {draft.transport === "stdio"
                ? "Secret environment values · JSON"
                : "Secret HTTP header values · JSON"}
            </span>
            <input
              type="password"
              value={secretInput}
              disabled={busy || running}
              placeholder={
                selectedSecret?.configured
                  ? "Configured — leave blank to keep current values"
                  : '{"GITHUB_TOKEN":"..."}'
              }
              onChange={(event) => {
                setSecretInput(event.target.value);
                setSecretAction(
                  event.target.value ? "set" : "keep"
                );
              }}
            />
            <small>
              {selectedSecret?.configured
                ? "Configured via " +
                  selectedSecret.mode.replace("_", " ")
                : selected?.secret_configured
                  ? "Configured via process environment."
                  : "No protected MCP secret configured."}
            </small>
          </label>

          {selectedSecret?.configured ? (
            <div className="settings-inline-actions">
              <button
                type="button"
                className="settings-secondary"
                disabled={busy || running}
                onClick={() => {
                  setSecretInput("");
                  setSecretAction("clear");
                  setMessage(
                    "MCP secrets will be cleared when this server is saved."
                  );
                }}
              >
                Clear protected secrets
              </button>
            </div>
          ) : null}

          <div className="mcp-trust-note">
            <strong>
              {draft.trusted ? "Trusted server" : "Untrusted by default"}
            </strong>
            <p>
              Trusted does not mean unrestricted. Only tools that declare
              read-only behavior and pass the local name-risk check can run
              without approval. Unknown or mutating tools remain gated.
            </p>
          </div>

          {selected?.status?.error ? (
            <div className="settings-warning">
              {selected.status.error}
            </div>
          ) : null}

          {selected && (selected.tools ?? []).length > 0 ? (
            <div className="mcp-tool-preview">
              <strong>Discovered tools</strong>
              {(selected.tools ?? []).map((tool) => (
                <div key={tool.name}>
                  <code>{tool.remote_tool}</code>
                  <span>
                    {tool.read_only ? "read-only" : tool.risk ?? "approval"}
                  </span>
                </div>
              ))}
            </div>
          ) : null}

          <div className="settings-bottom-actions">
            <button
              type="button"
              disabled={busy || running || !draft.name.trim()}
              onClick={() => void save()}
            >
              {draft.id ? "Save server" : "Add server"}
            </button>
            {draft.id ? (
              <button
                type="button"
                className="settings-secondary"
                disabled={busy || running}
                onClick={() => void remove()}
              >
                Delete server
              </button>
            ) : null}
          </div>
        </div>
      </div>
    </div>
  );
}
