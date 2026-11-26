import { describe, expect, it, vi } from "vitest";
import { OpenCodeRuntime } from "./openCodeRuntime";

describe("OpenCode production admission", () => {
  it("keeps production execution unavailable when the binary exists but gate is closed", async () => {
    const prev = process.env.LCA_ENABLE_OPENCODE_PRODUCTION;
    delete process.env.LCA_ENABLE_OPENCODE_PRODUCTION;
    const runtime = new OpenCodeRuntime();
    vi.spyOn(runtime, "resolveBinary").mockReturnValue("opencode.exe");
    expect(runtime.status()).toMatchObject({available: false, running: false, reason: "OpenCode production execution disabled: security and budget gates pending"});
    await expect(runtime.ensureStarted("{}")).rejects.toThrow("security and budget gates pending");
    if (prev === undefined) delete process.env.LCA_ENABLE_OPENCODE_PRODUCTION; else process.env.LCA_ENABLE_OPENCODE_PRODUCTION = prev;
  });
});
