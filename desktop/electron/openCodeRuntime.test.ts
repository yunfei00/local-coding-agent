import { describe, expect, it, vi } from "vitest";
import { OpenCodeRuntime } from "./openCodeRuntime";

describe("OpenCode production admission", () => {
  it("keeps production execution unavailable when the binary exists", async () => {
    const runtime = new OpenCodeRuntime();
    vi.spyOn(runtime, "resolveBinary").mockReturnValue("opencode.exe");
    expect(runtime.status()).toMatchObject({available: false, running: false});
    await expect(runtime.ensureStarted("{}")).rejects.toThrow("security and budget gates pending");
    expect(runtime.resolveBinary).not.toHaveBeenCalled();
  });
});
