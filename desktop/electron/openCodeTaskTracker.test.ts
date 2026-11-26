import {describe,it,expect} from "vitest";
import {OpenCodeTaskTracker} from "./openCodeTaskTracker";
describe("OpenCode task tracker",()=>{
 it("tracks progress, rejects concurrent tasks and preserves terminal state",()=>{
  const tracker=new OpenCodeTaskTracker(),id=tracker.begin("local");
  expect(()=>tracker.begin("other")).toThrow("running");
  tracker.progress(id);tracker.finish(id,"unknown");tracker.finish(id,"succeeded");tracker.progress(id);
  expect(tracker.list()[0]).toMatchObject({id,status:"unknown",events:1,verified:false});
  expect(tracker.begin("next")).not.toBe(id);
 });
});
