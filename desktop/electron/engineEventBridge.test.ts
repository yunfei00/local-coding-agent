import {describe,it,expect,vi} from "vitest";
import {translateEngineEvent,EngineEventBridge} from "./engineEventBridge";
describe("OpenCode event bridge",()=>{
  it("filters foreign sessions and never marks execution verified",()=>{
    const raw={data:{type:"session.execution.succeeded",data:{sessionID:"s"}}};
    expect(translateEngineEvent(raw,"other")).toBeUndefined();
    expect(translateEngineEvent(raw,"s")?.payload).toEqual({outcome:"succeeded",verified:false});
    expect(translateEngineEvent({data:{type:"session.text.delta",data:{sessionID:"s",delta:"中文"}}},"s")?.payload).toEqual({delta:"中文"});
  });
  it("maps permission and diff events",()=>{
    const approval=translateEngineEvent({data:{type:"permission.asked",data:{sessionID:"s",requestID:"r1",action:"file.write",resources:["a.txt"],message:"need write"}}},"s");
    expect(approval?.kind).toBe("approval");
    expect((approval?.payload as any).requestId).toBe("r1");
    const diff=translateEngineEvent({data:{type:"session.diff",data:{sessionID:"s",diff:[{path:"a.txt"}]}}},"s");
    expect(diff?.kind).toBe("diff");
  });
  it("reconciles snapshot and fails closed on stream loss",async()=>{
    const source={events:vi.fn(async()=>new Response('data: {"type":"session.execution.interrupted","data":{"sessionID":"s"}}\n\n')),request:vi.fn(async()=>({data:{id:"s",outcome:"interrupted"}}))};
    const emit=vi.fn();
    await expect(new EngineEventBridge(source,0).follow("s",new AbortController().signal,emit)).rejects.toThrow("recovery exhausted");
    expect(emit.mock.calls.map(call=>call[0].kind)).toEqual(["snapshot","execution-ended","disconnected"]);
    expect(source.request).toHaveBeenCalledWith("/api/session/s");
  });
});
