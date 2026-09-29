export type DiagnosticValue =
  | null
  | boolean
  | number
  | string
  | DiagnosticValue[]
  | { [key: string]: DiagnosticValue };

const SENSITIVE_KEY = /(api[_-]?key|token|secret|password|authorization|prompt|messages?)/i;
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
