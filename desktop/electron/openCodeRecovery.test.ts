import {describe,it,expect,vi} from "vitest";
import {inspectOriginalSession} from "./openCodeRecovery";
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
