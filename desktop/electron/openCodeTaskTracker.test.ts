import {mkdtempSync,rmSync} from "node:fs";
import os from "node:os";
import path from "node:path";
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

describe("persistent lifecycle",()=>{
 it("recovers unfinished work as unknown without replay",()=>{
  const root=mkdtempSync(path.join(os.tmpdir(),"lca-journal-"));
  try{
   const file=path.join(root,"tasks.json"),a=new OpenCodeTaskTracker(file),id=a.begin("local");
   a.bindSession(id,"session-original","opencode-chat-abcdef");
   expect(()=>a.bindSession(id,"session-other","opencode-chat-abcdef")).toThrow();
   a.transition(id,"waiting");
   expect(()=>a.begin("other")).toThrow();
   a.transition(id,"running");a.transition(id,"stopping");a.transition(id,"running");
   expect(a.list()[0].status).toBe("stopping");
   const b=new OpenCodeTaskTracker(file);
   expect(b.list()[0]).toMatchObject({id,status:"unknown",verified:false,sessionId:"session-original",storageId:"opencode-chat-abcdef"});
   b.finish(id,"succeeded");
   expect(b.list()[0].status).toBe("unknown");
  }finally{rmSync(root,{recursive:true,force:true});}
 });
});
