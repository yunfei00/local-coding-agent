import { useState } from "react";
import { formatTurnTrace } from "../lib/diagnostics";

export type TurnTrace = { provider?: string; model?: string; execution_summary?: {
  model_steps?: number; tool_calls?: number; tool_duration_ms?: number;
  tool_failures?: number; provider_retries?: number; elapsed_ms?: number;
  context_token_estimate?: number; context_sources?: Record<string, number>;
} };

export function ExecutionSummary({ trace }: { trace: TurnTrace }) {
  const [copied, setCopied] = useState(false);
  const [error, setError] = useState("");
  const metrics = trace.execution_summary;
  if (!metrics) return null;
  return <details className="execution-summary">
    <summary>{trace.model} · {metrics.model_steps ?? 0} steps · {metrics.tool_calls ?? 0} tools · {((metrics.elapsed_ms ?? 0) / 1000).toFixed(1)}s</summary>
    <div className="execution-summary-body">
      <span>{trace.provider} · Tools {metrics.tool_duration_ms ?? 0} ms · Failures {metrics.tool_failures ?? 0} · Retries {metrics.provider_retries ?? 0}</span>
      <span>Context ≈ {metrics.context_token_estimate ?? 0} tokens</span>
      <div>{Object.entries(metrics.context_sources ?? {}).map(([source, count]) => <span className="context-source" key={source}>{source.replaceAll("_", " ")}: {count}</span>)}</div>
      <button type="button" onClick={() => {
        void window.localAgent.copyDiagnostics(formatTurnTrace(trace)).then(() => setCopied(true)).catch(cause => setError(String(cause)));
      }}>{copied ? "Copied" : "Copy sanitized trace"}</button>
      {error && <span role="alert">{error}</span>}
    </div>
  </details>;
}
