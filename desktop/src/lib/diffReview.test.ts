import { describe, expect, it } from "vitest";

import {
  diffPreviewState,
  diffStatusLabel,
  resolveSelectedDiffPath
} from "./diffReview";

describe("diff review helpers", () => {
  it("maps file statuses to compact labels", () => {
    expect(diffStatusLabel("modified")).toBe("M");
    expect(diffStatusLabel("added")).toBe("A");
    expect(diffStatusLabel("deleted")).toBe("D");
    expect(diffStatusLabel("renamed")).toBe("R");
    expect(diffStatusLabel("untracked")).toBe("U");
  });

  it("keeps the current selection when the file still exists", () => {
    const files = [
      { path: "a.py" },
      { path: "b.py" }
    ];

    expect(resolveSelectedDiffPath(files, "b.py")).toBe("b.py");
  });

  it("falls back to the first file when the selection disappears", () => {
    const files = [
      { path: "a.py" },
      { path: "b.py" }
    ];

    expect(resolveSelectedDiffPath(files, "missing.py")).toBe("a.py");
  });

  it("reports binary and truncated preview flags", () => {
    expect(
      diffPreviewState({
        path: "blob.bin",
        binary: true,
        truncated: true
      })
    ).toEqual(["binary", "truncated"]);
  });
});
