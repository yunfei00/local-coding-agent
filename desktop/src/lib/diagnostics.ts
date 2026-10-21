export type DiagnosticValue =
  | null
  | boolean
  | number
  | string
  | DiagnosticValue[]
  | { [key: string]: DiagnosticValue };

const SENSITIVE_KEY = /(api[_-]?key|(?:^|[_-])(?:access_token|refresh_token|auth_token|token_value)(?:$|[_-])|secret|password|authorization|prompt|messages?)/i;
const SECRET_PATTERNS = [
  /(Bearer\s+)[A-Za-z0-9._~+/=-]+/gi,
  /\bsk-[A-Za-z0-9_-]{8,}\b/g,
  /((?:api[_-]?key|access[_-]?token|secret|password)\s*[:=]\s*)[^\s,;]+/gi
];

function sanitizeString(value: string): string {
  let next = value;
  for (const pattern of SECRET_PATTERNS) {
    next = next.replace(pattern, (_match, prefix?: string) =>
      (prefix ?? "") + "<REDACTED>"
    );
  }
  return next;
}

export function sanitizeDiagnostics(value: unknown): DiagnosticValue {
  if (value === null || value === undefined) {
    return null;
  }
  if (
    typeof value === "boolean" ||
    typeof value === "number"
  ) {
    return value;
  }
  if (typeof value === "string") {
    return sanitizeString(value);
  }
  if (Array.isArray(value)) {
    return value.map((item) => sanitizeDiagnostics(item));
  }
  if (typeof value === "object") {
    const result: Record<string, DiagnosticValue> = {};
    for (const [key, item] of Object.entries(
      value as Record<string, unknown>
    )) {
      if (SENSITIVE_KEY.test(key)) {
        if (
          key === "prompt_rules" ||
          key === "redaction" ||
          (key === "messages" && typeof item === "number")
        ) {
          result[key] = sanitizeDiagnostics(item);
        } else {
          result[key] = "<REDACTED>";
        }
        continue;
      }
      result[key] = sanitizeDiagnostics(item);
    }
    return result;
  }
  return sanitizeString(String(value));
}

export function formatDiagnosticsReport(value: unknown): string {
  const safe = sanitizeDiagnostics(value);
  return [
    "Local Coding Agent Diagnostics",
    "Generated report is redacted for support sharing.",
    "",
    JSON.stringify(safe, null, 2)
  ].join("\n");
}

/** Export only allowlisted numeric metrics; never include prompts or tool payloads. */
export function formatTurnTrace(
  turn: Record<string, unknown>
): string {
  const allowed = ["provider", "model", "finish_reason", "model_steps",
    "tool_calls", "prompt_eval_count", "eval_count"];
  const safe: Record<string, unknown> = {};
  for (const key of allowed) {
    const value = turn[key];
    if (typeof value === "number" && Number.isFinite(value)) {
      safe[key] = value;
    } else if (typeof value === "string" && key !== "model") {
      safe[key] = value.slice(0, 100);
    } else if (key === "model" && typeof value === "string") {
      safe[key] = value.slice(0, 100);
    }
  }
  const summary = turn.execution_summary;
  if (summary && typeof summary === "object" && !Array.isArray(summary)) {
    const metrics: Record<string, number> = {};
    for (const key of ["elapsed_ms", "tool_duration_ms", "tool_failures",
      "provider_retries", "model_steps", "tool_calls"]) {
      const value = (summary as Record<string, unknown>)[key];
      if (typeof value === "number" && Number.isFinite(value)) {
        metrics[key] = value;
      }
    }
    safe.execution_summary = metrics;
  }
  return JSON.stringify(sanitizeDiagnostics(safe), null, 2);
}
