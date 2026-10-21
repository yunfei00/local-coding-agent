import { describe, expect, it } from "vitest";

import {
  formatDiagnosticsReport,
  formatTurnTrace,
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

describe("phase27 execution trace", () => {
  it("redacts credentials, URLs, environment and reasoning fields", () => {
    const safe = JSON.stringify(sanitizeDiagnostics({
      mcp_credentials: "private-mcp", env: { CUSTOM_SECRET: "private-env" },
      reasoning: "private-thought", message: "Authorization: Basic private-basic",
      url: "https://user:private-pass@example.test/path?token=private-token",
      context_token_estimate: 123,
    }));
    for (const secret of ["private-mcp", "private-env", "private-thought", "private-basic", "private-pass", "private-token"]) expect(safe).not.toContain(secret);
    expect(safe).toContain("123");
  });
  it("keeps token accounting without exposing secrets", () => {
    const safe = sanitizeDiagnostics({
      context: { estimated_input_tokens: 123, context_sources: { history: 40 } },
      access_token: "do-not-export"
    });
    expect(JSON.stringify(safe)).toContain('"estimated_input_tokens":123');
    expect(JSON.stringify(safe)).not.toContain("do-not-export");
  });

  it("exports only allowlisted turn metrics", () => {
    const trace = formatTurnTrace({
      provider: "ollama", model: "qwen",
      model_steps: 4, tool_calls: 2,
      prompt: "private prompt", tool_arguments: "secret",
      execution_summary: { elapsed_ms: 125, tool_failures: 1,
        tool_output: "secret-output" }
    });
    expect(trace).toContain('"elapsed_ms": 125');
    expect(trace).not.toContain("private prompt");
    expect(trace).not.toContain("secret-output");
    expect(trace).not.toContain("secret");
  });
});
