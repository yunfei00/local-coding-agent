import { useEffect, useMemo, useState } from "react";

import { formatDiagnosticsReport } from "../lib/diagnostics";

type Props = {
  onClose: () => void;
};

type DiagnosticPayload = Record<string, unknown>;

type DiagnosticBundle = {
  agent: DiagnosticPayload;
  desktop: Record<string, unknown>;
};

function objectValue(
  value: unknown
): Record<string, unknown> {
  return value && typeof value === "object"
    ? (value as Record<string, unknown>)
    : {};
}

function stringValue(value: unknown, fallback = "—"): string {
  if (value === null || value === undefined || value === "") {
    return fallback;
  }
  return String(value);
}

function booleanLabel(value: unknown): string {
  return value ? "Yes" : "No";
}

export function DiagnosticsPanel({ onClose }: Props) {
  const [bundle, setBundle] = useState<DiagnosticBundle | null>(null);
  const [busy, setBusy] = useState(false);
  const [copied, setCopied] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = async () => {
    setBusy(true);
    setError(null);
    try {
      const result = await window.localAgent.getDiagnostics();
      setBundle({
        agent: result.event.payload ?? {},
        desktop: result.desktop
      });
    } catch (nextError) {
      setError(String(nextError));
    } finally {
      setBusy(false);
    }
  };

  useEffect(() => {
    void load();
  }, []);

  const report = useMemo(
    () =>
      bundle
        ? formatDiagnosticsReport({
            desktop: bundle.desktop,
            agent: bundle.agent
          })
        : "",
    [bundle]
  );

  const application = objectValue(bundle?.agent.application);
  const runtime = objectValue(bundle?.agent.runtime);
  const provider = objectValue(bundle?.agent.provider);
  const context = objectValue(bundle?.agent.context);
  const permission = objectValue(bundle?.agent.permission);
  const workspace = objectValue(bundle?.agent.workspace);
  const detection = objectValue(workspace.detection);
  const database = objectValue(bundle?.agent.database);
  const counts = objectValue(database.counts);
  const promptRules = objectValue(bundle?.agent.prompt_rules);
  const mcp = objectValue(bundle?.agent.mcp);
  const mcpServers = Array.isArray(mcp.servers)
    ? (mcp.servers as unknown[])
    : [];
  const redaction = objectValue(bundle?.agent.redaction);
  const recentErrors = Array.isArray(bundle?.agent.recent_errors)
    ? (bundle?.agent.recent_errors as unknown[])
    : [];

  const copy = async () => {
    if (!report) {
      return;
    }
    setError(null);
    try {
      await window.localAgent.copyDiagnostics(report);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1800);
    } catch (nextError) {
      setError(String(nextError));
    }
  };

  return (
    <section className="diagnostics-panel">
      <header className="diagnostics-header">
        <div>
          <div className="eyebrow">LOCAL CODING AGENT</div>
          <h1>Diagnostics</h1>
        </div>
        <div className="diagnostics-actions">
          <button
            type="button"
            disabled={busy}
            onClick={() => void load()}
          >
            {busy ? "Refreshing…" : "Refresh"}
          </button>
          <button
            type="button"
            disabled={!report}
            onClick={() => void copy()}
          >
            {copied ? "Copied" : "Copy report"}
          </button>
          <button type="button" onClick={onClose}>
            Close
          </button>
        </div>
      </header>

      <div className="diagnostics-content">
        {error ? <div className="error-banner">{error}</div> : null}

        {!bundle ? (
          <div className="diagnostics-loading">
            {busy ? "Collecting diagnostics…" : "Diagnostics unavailable."}
          </div>
        ) : (
          <>
            <div className="diagnostics-grid">
              <section className="diagnostics-card">
                <h2>Application</h2>
                <dl>
                  <div>
                    <dt>Version</dt>
                    <dd>{stringValue(application.version)}</dd>
                  </div>
                  <div>
                    <dt>Protocol</dt>
                    <dd>{stringValue(application.protocol)}</dd>
                  </div>
                  <div>
                    <dt>Desktop</dt>
                    <dd>{stringValue(bundle.desktop.app_version)}</dd>
                  </div>
                  <div>
                    <dt>Packaged</dt>
                    <dd>{booleanLabel(bundle.desktop.packaged)}</dd>
                  </div>
                </dl>
              </section>

              <section className="diagnostics-card">
                <h2>Platform</h2>
                <dl>
                  <div>
                    <dt>OS</dt>
                    <dd>
                      {stringValue(runtime.platform)}{" "}
                      {stringValue(runtime.platform_release, "")}
                    </dd>
                  </div>
                  <div>
                    <dt>Architecture</dt>
                    <dd>{stringValue(runtime.architecture)}</dd>
                  </div>
                  <div>
                    <dt>Python</dt>
                    <dd>{stringValue(runtime.python)}</dd>
                  </div>
                  <div>
                    <dt>Electron</dt>
                    <dd>{stringValue(bundle.desktop.electron)}</dd>
                  </div>
                </dl>
              </section>

              <section className="diagnostics-card">
                <h2>Provider</h2>
                <dl>
                  <div>
                    <dt>Name</dt>
                    <dd>{stringValue(provider.provider)}</dd>
                  </div>
                  <div>
                    <dt>Online</dt>
                    <dd>{booleanLabel(provider.online)}</dd>
                  </div>
                  <div>
                    <dt>Model</dt>
                    <dd>
                      {stringValue(
                        provider.default_model ?? provider.preferred_model
                      )}
                    </dd>
                  </div>
                  <div>
                    <dt>Models</dt>
                    <dd>{stringValue(provider.model_count, "0")}</dd>
                  </div>
                </dl>
                {provider.error ? (
                  <div className="diagnostics-inline-error">
                    {stringValue(
                      objectValue(provider.error).message,
                      "Provider error"
                    )}
                  </div>
                ) : null}
              </section>

              <section className="diagnostics-card">
                <h2>Context</h2>
                <dl>
                  <div>
                    <dt>Window</dt>
                    <dd>{stringValue(context.window_tokens)}</dd>
                  </div>
                  <div>
                    <dt>Reserved output</dt>
                    <dd>{stringValue(context.reserved_output_tokens)}</dd>
                  </div>
                  <div>
                    <dt>Permission</dt>
                    <dd>{stringValue(permission.mode)}</dd>
                  </div>
                  <div>
                    <dt>Last usage</dt>
                    <dd>
                      {context.last_usage
                        ? stringValue(
                            objectValue(context.last_usage)
                              .estimated_input_tokens
                          )
                        : "No completed context sample"}
                    </dd>
                  </div>
                </dl>
              </section>

              <section className="diagnostics-card diagnostics-wide">
                <h2>Workspace</h2>
                {bundle.agent.workspace ? (
                  <dl>
                    <div>
                      <dt>Name</dt>
                      <dd>{stringValue(workspace.name)}</dd>
                    </div>
                    <div>
                      <dt>Path</dt>
                      <dd className="diagnostics-mono">
                        {stringValue(workspace.path)}
                      </dd>
                    </div>
                    <div>
                      <dt>Detected</dt>
                      <dd>
                        {Array.isArray(detection.detected)
                          ? detection.detected.join(", ") || "None"
                          : "None"}
                      </dd>
                    </div>
                    <div>
                      <dt>Threads</dt>
                      <dd>{stringValue(workspace.thread_count, "0")}</dd>
                    </div>
                  </dl>
                ) : (
                  <p>No active workspace.</p>
                )}
              </section>

              <section className="diagnostics-card">
                <h2>MCP</h2>
                <dl>
                  <div>
                    <dt>Servers</dt>
                    <dd>{stringValue(mcp.server_count, "0")}</dd>
                  </div>
                  <div>
                    <dt>Enabled</dt>
                    <dd>{stringValue(mcp.enabled_count, "0")}</dd>
                  </div>
                  <div>
                    <dt>Connected</dt>
                    <dd>{stringValue(mcp.connected_count, "0")}</dd>
                  </div>
                  <div>
                    <dt>Tools</dt>
                    <dd>{stringValue(mcp.tool_count, "0")}</dd>
                  </div>
                </dl>
                {mcpServers.length > 0 ? (
                  <div className="diagnostics-mcp-list">
                    {mcpServers.map((raw, index) => {
                      const item = objectValue(raw);
                      return (
                        <div key={stringValue(item.name, String(index))}>
                          <span
                            className={
                              "mcp-status-dot " +
                              (item.connected ? "online" : "offline")
                            }
                          />
                          <strong>{stringValue(item.name)}</strong>
                          <span>
                            {item.connected ? "connected" : "offline"}
                            {" · "}
                            {stringValue(item.tool_count, "0")} tools
                          </span>
                        </div>
                      );
                    })}
                  </div>
                ) : null}
              </section>

              <section className="diagnostics-card">
                <h2>Database</h2>
                <dl>
                  <div>
                    <dt>Schema</dt>
                    <dd>{stringValue(database.schema_version)}</dd>
                  </div>
                  <div>
                    <dt>Quick check</dt>
                    <dd>{stringValue(database.quick_check)}</dd>
                  </div>
                  <div>
                    <dt>Messages</dt>
                    <dd>{stringValue(counts.messages, "0")}</dd>
                  </div>
                  <div>
                    <dt>Tool calls</dt>
                    <dd>{stringValue(counts.tool_calls, "0")}</dd>
                  </div>
                </dl>
              </section>

              <section className="diagnostics-card">
                <h2>Prompt Rules</h2>
                <dl>
                  {["global", "project", "thread"].map((scope) => {
                    const item = objectValue(promptRules[scope]);
                    return (
                      <div key={scope}>
                        <dt>{scope}</dt>
                        <dd>
                          {item.configured
                            ? item.enabled
                              ? "Configured · enabled"
                              : "Configured · disabled"
                            : "Not configured"}
                        </dd>
                      </div>
                    );
                  })}
                </dl>
              </section>
            </div>

            <section className="diagnostics-errors">
              <div className="diagnostics-section-title">
                <div>
                  <h2>Recent sanitized errors</h2>
                  <p>
                    Only error metadata is retained here. Chat content and
                    Prompt Rule text are excluded.
                  </p>
                </div>
                <span>{recentErrors.length}</span>
              </div>

              {recentErrors.length === 0 ? (
                <div className="diagnostics-empty">No recent errors.</div>
              ) : (
                <div className="diagnostics-error-list">
                  {recentErrors.map((raw, index) => {
                    const item = objectValue(raw);
                    return (
                      <div
                        className="diagnostics-error-row"
                        key={
                          stringValue(item.timestamp, String(index)) +
                          ":" +
                          index
                        }
                      >
                        <div>
                          <strong>{stringValue(item.code)}</strong>
                          <span>{stringValue(item.source)}</span>
                        </div>
                        <p>{stringValue(item.message)}</p>
                      </div>
                    );
                  })}
                </div>
              )}
            </section>

            <section className="diagnostics-redaction">
              <strong>Redaction active</strong>
              <span>
                API keys {booleanLabel(redaction.api_keys)} · MCP credentials{" "}
                {booleanLabel(redaction.mcp_credentials)} · Prompt Rule
                content {booleanLabel(redaction.prompt_rule_content)} · Chat
                history {booleanLabel(redaction.chat_history)} · Home path{" "}
                {booleanLabel(redaction.home_path)}
              </span>
            </section>

            <details className="diagnostics-report-preview">
              <summary>Preview copied report</summary>
              <pre>{report}</pre>
            </details>
          </>
        )}
      </div>
    </section>
  );
}
