import { describe, expect, it } from "vitest";

import { formatAgentStatus } from "./status";

describe("formatAgentStatus", () => {
  it("formats the ready state", () => {
    expect(formatAgentStatus("ready")).toBe("Agent Connected");
  });

  it("formats an error state", () => {
    expect(formatAgentStatus("error")).toBe("Agent Error");
  });
});
