import { describe, expect, it } from "vitest";

import {
  checkForUpdates,
  compareVersions,
  releaseResult
} from "./updateCheck";

describe("manual update check policy", () => {
  it("compares semantic versions", () => {
    expect(compareVersions("0.2.0", "0.1.0")).toBe(1);
    expect(compareVersions("v0.1.0", "0.1.0")).toBe(0);
    expect(compareVersions("0.1.0", "0.2.0")).toBe(-1);
  });

  it("reports an available release without install capabilities", () => {
    const result = releaseResult("0.1.0", {
      tag_name: "v0.2.0",
      html_url:
        "https://github.com/yunfei00/local-coding-agent/releases/tag/v0.2.0"
    });

    expect(result.ok).toBe(true);
    expect(result.update_available).toBe(true);
    expect(result.latest_version).toBe("0.2.0");
    expect(result.automatic).toBe(false);
    expect(result.can_auto_download).toBe(false);
    expect(result.can_auto_install).toBe(false);
  });

  it("does not treat an older release as an update", () => {
    const result = releaseResult("0.2.0", {
      tag_name: "v0.1.0",
      html_url:
        "https://github.com/yunfei00/local-coding-agent/releases/tag/v0.1.0"
    });

    expect(result.ok).toBe(true);
    expect(result.update_available).toBe(false);
  });

  it("rejects draft or prerelease metadata for the stable channel", () => {
    expect(
      releaseResult("0.1.0", {
        tag_name: "v0.2.0-beta.1",
        prerelease: true
      }).ok
    ).toBe(false);
    expect(
      releaseResult("0.1.0", {
        tag_name: "v0.2.0",
        draft: true
      }).ok
    ).toBe(false);
  });

  it("fails safely when offline", async () => {
    const result = await checkForUpdates("0.1.0", {
      url: "https://127.0.0.1:1/releases/latest",
      timeoutMs: 100
    });

    expect(result.ok).toBe(false);
    expect(result.update_available).toBe(false);
    expect(result.error).toBeTruthy();
    expect(result.automatic).toBe(false);
    expect(result.can_auto_download).toBe(false);
    expect(result.can_auto_install).toBe(false);
  });
});
