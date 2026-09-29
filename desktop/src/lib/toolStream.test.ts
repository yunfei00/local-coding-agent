import { describe, expect, it } from "vitest";

import { appendOrderedToolChunk } from "./toolStream";

describe("appendOrderedToolChunk", () => {
  it("orders out-of-order stream events by sequence", () => {
    let state = appendOrderedToolChunk(
      [],
      { stream: "stderr", text: "second\n", sequence: 2 },
      100
    );
    state = appendOrderedToolChunk(
      state.chunks,
      { stream: "stdout", text: "first\n", sequence: 1 },
      100
    );

    expect(state.chunks.map((chunk) => chunk.sequence)).toEqual([1, 2]);
    expect(state.chunks.map((chunk) => chunk.text).join("")).toBe(
      "first\nsecond\n"
    );
  });

  it("deduplicates retransmitted sequence numbers", () => {
    let state = appendOrderedToolChunk(
      [],
      { stream: "stdout", text: "old", sequence: 1 },
      100
    );
    state = appendOrderedToolChunk(
      state.chunks,
      { stream: "stdout", text: "new", sequence: 1 },
      100
    );

    expect(state.chunks).toEqual([
      { stream: "stdout", text: "new", sequence: 1 }
    ]);
  });

  it("drops oldest rendered output when the UI budget is exceeded", () => {
    let state = appendOrderedToolChunk(
      [],
      { stream: "stdout", text: "123456", sequence: 1 },
      10
    );
    state = appendOrderedToolChunk(
      state.chunks,
      { stream: "stderr", text: "abcdef", sequence: 2 },
      10
    );

    expect(state.droppedChars).toBe(6);
    expect(state.chunks).toEqual([
      { stream: "stderr", text: "abcdef", sequence: 2 }
    ]);
  });

  it("trims a single oversized chunk from the head", () => {
    const state = appendOrderedToolChunk(
      [],
      { stream: "stdout", text: "0123456789", sequence: 1 },
      4
    );

    expect(state.droppedChars).toBe(6);
    expect(state.chunks[0].text).toBe("6789");
  });
});
