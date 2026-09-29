import { describe, expect, it } from "vitest";

import { shouldSubmitComposer } from "./composer";

describe("shouldSubmitComposer", () => {
  it("submits on plain Enter", () => {
    expect(
      shouldSubmitComposer({
        key: "Enter",
        shiftKey: false,
        isComposing: false
      })
    ).toBe(true);
  });

  it("keeps Shift+Enter for a newline", () => {
    expect(
      shouldSubmitComposer({
        key: "Enter",
        shiftKey: true,
        isComposing: false
      })
    ).toBe(false);
  });

  it("does not submit while IME composition is active", () => {
    expect(
      shouldSubmitComposer({
        key: "Enter",
        shiftKey: false,
        isComposing: true
      })
    ).toBe(false);
  });
});
