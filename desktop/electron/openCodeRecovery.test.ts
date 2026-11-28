import {describe,it,expect,vi} from "vitest";
import {inspectOriginalSession,recoverCompletedExchange} from "./openCodeRecovery";
describe("original session recovery",()=>{
 it("only reads original identity and active state",async()=>{
  const request=vi.fn(async(route:string)=>route.endsWith("/active")?{}:{data:{id:"original",outcome:"interrupted"}});
  expect(await inspectOriginalSession({request},"original")).toMatchObject({active:false,outcome:"interrupted",canResume:false,verified:false});
  expect(request.mock.calls).toEqual([["/api/session/original"],["/api/session/active"]]);
 });
 it("rejects mismatched identity",async()=>{
  await expect(inspectOriginalSession({request:async()=>({data:{id:"other"}})},"original")).rejects.toThrow("identity");
 });
 it("never authorizes resume even when active",async()=>{
  const request=async(route:string)=>route.endsWith("/active")?{original:{}}:{data:{id:"original"}};
  expect(await inspectOriginalSession({request},"original")).toMatchObject({active:true,canResume:false});
 });
});

it("requires the current admitted message and its own terminal marker", () => {
  const stale = {type:"idle",outcome:"succeeded"};
  const user = {type:"user",id:"msg_current"};
  const reply = {type:"assistant",content:[{type:"reasoning",text:"do not use"},{type:"tool",text:"discard"},{type:"text",text:"real reply"}]};
  expect(recoverCompletedExchange({data:[stale,user,reply]},user.id)).toBeUndefined();
  expect(recoverCompletedExchange({data:[stale,user,reply,stale]},"msg_other")).toBeUndefined();
  expect(recoverCompletedExchange({data:[stale,user,reply,stale]},user.id)).toEqual({outcome:"succeeded",text:"real reply"});
  expect(recoverCompletedExchange({data:[user,{type:"idle",outcome:"failed"},reply,stale]},user.id)).toEqual({outcome:"failed",text:""});
});
