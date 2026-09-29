import { describe, expect, it } from "vitest";

import {
  formatDiagnosticsReport,
  sanitizeDiagnostics
} from "./diagnostics";

describe("diagnostics redaction", () => {
  it("redacts sensitive keys and string patterns", () => {
    const safe = sanitizeDiagnostics({
      api_key: "top-secret",
      nested: {
        authorization: "Bearer abc123",
        note: "password=hello"
      },
      database: {
        counts: {
          messages: 42
        }
      },
      prompt_rules: {
        global: {
          configured: true,
          enabled: true
        }
      }
    }) as Record<string, unknown>;

    expect(safe.api_key).toBe("<REDACTED>");
    expect(JSON.stringify(safe)).not.toContain("top-secret");
    expect(JSON.stringify(safe)).not.toContain("abc123");
    expect(JSON.stringify(safe)).not.toContain("password=hello");
    expect(JSON.stringify(safe)).toContain('"messages":42');
    expect(JSON.stringify(safe)).toContain('"prompt_rules"');
  });

  it("formats a shareable report without secret values", () => {
    const report = formatDiagnosticsReport({
      provider: "ollama",
      access_token: "token-value",
      error: "Bearer abc999"
    });

    expect(report).toContain("Local Coding Agent Diagnostics");
    expect(report).toContain("<REDACTED>");
    expect(report).not.toContain("token-value");
    expect(report).not.toContain("abc999");
  });
});
