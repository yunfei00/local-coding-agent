import { describe, it, expect } from "vitest";
import { OpenCodeUpdateManager } from "./openCodeUpdateManager";

describe("OpenCode update manager", () => {
  it("returns current version from lock file", () => {
    const mgr = new OpenCodeUpdateManager(require("os").tmpdir());
    const v = mgr.getCurrentVersion();
    expect(typeof v).toBe("string");
    expect(v.length).toBeGreaterThan(0);
  });

  it("checkForUpdates returns no auto-update by default", async () => {
    const mgr = new OpenCodeUpdateManager();
    const info = await mgr.checkForUpdates();
    expect(info.updateAvailable).toBe(false);
  });

  it("verifyChecksum returns false for missing file", () => {
    const mgr = new OpenCodeUpdateManager();
    expect(mgr.verifyChecksum("/nonexistent/file", "abc123")).toBe(false);
  });

  it("checkCompatibility returns all passed", () => {
    const mgr = new OpenCodeUpdateManager();
    const compat = mgr.checkCompatibility("2.2.6");
    expect(compat.allPassed).toBe(true);
    expect(compat.api).toBe(true);
    expect(compat.sse).toBe(true);
    expect(compat.permissions).toBe(true);
    expect(compat.modelConfig).toBe(true);
  });

  it("isUpgrading returns false initially", () => {
    const mgr = new OpenCodeUpdateManager();
    expect(mgr.isUpgrading()).toBe(false);
  });

  it("upgrade succeeds for compatible version", async () => {
    const mgr = new OpenCodeUpdateManager();
    const result = await mgr.upgrade("2.2.7", "https://example.com/opencode.zip", "abc123");
    expect(result.success).toBe(true);
    expect(result.rolledBack).toBe(false);
  });
});