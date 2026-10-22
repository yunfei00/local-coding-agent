import {describe, expect, it} from "vitest";
import {mergeTaskSnapshot, taskIsActive, TaskSnapshot} from "./autonomousTask";

describe("durable task state", () => {
  const task = {id:"one", thread_id:"thread", revision:5, status:"paused"} as TaskSnapshot;
  it("rejects stale snapshots and other threads", () => {
    expect(mergeTaskSnapshot([task], {...task, revision:4, status:"executing"}, "thread")).toEqual([task]);
    expect(mergeTaskSnapshot([task], {...task, thread_id:"other", revision:6}, "thread")).toEqual([task]);
  });
  it("accepts current backend state and retains distinct tasks", () => {
    expect(mergeTaskSnapshot([task], {...task, revision:6, status:"awaiting_approval"}, "thread")[0].status).toBe("awaiting_approval");
    expect(mergeTaskSnapshot([task], {...task, id:"two"}, "thread")).toHaveLength(2);
  });
  it("keeps paused and failed executions resumable without calling them completed", () => {
    expect(taskIsActive(task)).toBe(false);
    expect(taskIsActive({status:"verifying"})).toBe(true);
    expect(taskIsActive({status:"failed"})).toBe(false);
  });
});
