import {describe,it,expect} from "vitest";
import {summarizeToolEvent} from "./toolEventSummary";
describe("tool event metadata",()=>{
 it("correlates safe identifiers without exposing sensitive payloads",()=>{
  const event=summarizeToolEvent("session.tool.success",{callID:"call-1",toolName:"shell",input:{token:"SECRET"},output:"SECRET",error:"SECRET"});
  expect(event).toMatchObject({callId:"call-1",name:"shell",input:"结构化数据（内容未公开）"});
  expect(JSON.stringify(event)).not.toContain("SECRET");
 });
 it("rejects malformed identifiers",()=>expect(summarizeToolEvent("session.tool.call",{callID:"bad\nidentifier"}).callId).toBeUndefined());
});
