import { describe, expect, it, vi } from "vitest";
import { OpenCodeRuntime } from "./openCodeRuntime";

describe("OpenCode production admission", () => {
  it("keeps production execution available when binary exists (RC2)", async () => {
    const runtime = new OpenCodeRuntime();
    vi.spyOn(runtime, "resolveBinary").mockReturnValue("opencode.exe");
    expect(runtime.status()).toMatchObject({ available: true, running: false });
  });
});