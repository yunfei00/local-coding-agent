import { describe, expect, it } from "vitest";

import {
  DESKTOP_PROTOCOL_VERSION,
  checkProtocolCompatibility
} from "./protocol";

describe("protocol compatibility", () => {
  it("uses semantic protocol versioning", () => {
    expect(DESKTOP_PROTOCOL_VERSION).toBe("1.0.0");
  });

  it("accepts the supported major version", () => {
    expect(checkProtocolCompatibility("1.0.0").compatible).toBe(true);
    expect(checkProtocolCompatibility("1.9.4").compatible).toBe(true);
  });

  it("rejects a future incompatible major", () => {
    const result = checkProtocolCompatibility("2.0.0");
    expect(result.compatible).toBe(false);
    expect(result.reason).toContain("Unsupported Agent protocol 2.0.0");
  });

  it("rejects legacy and malformed protocol labels", () => {
    expect(checkProtocolCompatibility("phase9").compatible).toBe(false);
    expect(checkProtocolCompatibility("1").compatible).toBe(false);
    expect(checkProtocolCompatibility("").compatible).toBe(false);
  });
});
