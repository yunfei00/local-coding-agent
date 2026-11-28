import { describe, expect, it, vi } from "vitest";
import { EngineRouter, LegacyAdapter, OpenCodeAdapter } from "./engineAdapter";

describe("engine contract", () => {
  it("creates deny-all sessions and sends prompt", async () => {
    const request = vi.fn(async (route: string) => route === "/api/session" ? ({data: {id: "s"}}) : undefined);
    const engine = new OpenCodeAdapter(request);
    expect(await engine.create("fixture", "test")).toBe("s");
    expect(request).toHaveBeenCalledWith("/api/session", "POST", {title:"test", permissions:[{action:"*",resource:"*",effect:"deny"}]});
    await engine.send("s", "hello");
    expect(request).toHaveBeenCalledWith("/api/session/s/prompt", "POST", {text:"hello"});
  });

  it("defaults to legacy and rejects admission-only OpenCode routing", async () => {
    const send = vi.fn(async () => {});
    const legacy = new LegacyAdapter({create:async()=>"l",status:async()=>null,send,cancel:async()=>null});
    const opRequest = vi.fn(async (route: string) => route === "/api/session" ? ({data:{id:"s"}}) : undefined);
    const router = new EngineRouter(legacy,new OpenCodeAdapter(opRequest));
    expect(router.engine()).toBe(legacy);
    await router.run({threadId:"t",engine:"legacy",sessionId:"l",projectRoot:process.cwd()},"hello");
    expect(send).toHaveBeenCalledWith("l","hello");
    await expect(router.run({
      threadId:"t2",engine:"opencode",sessionId:"s",projectRoot:process.cwd(),
    },"hello")).rejects.toThrow("disabled");
    expect(opRequest).not.toHaveBeenCalled();
  });

  it("holds the workspace lease until execution settles, including failure",async()=>{
    let finish!:()=>void;
    let admitted!:()=>void;
    const entered=new Promise<void>(resolve=>{admitted=resolve;});
    const execution=new Promise<void>(resolve=>{finish=resolve;});
    const send=vi.fn(async()=>{admitted();await execution;throw new Error("execution failed");});
    const router=new EngineRouter(new LegacyAdapter({create:async()=>"l",status:async()=>null,send,cancel:async()=>null}),new OpenCodeAdapter(async()=>null));
    const binding={threadId:"a",engine:"legacy" as const,sessionId:"l",projectRoot:process.cwd()};
    const first=router.run(binding,"first");
    const failure=expect(first).rejects.toThrow("execution failed");
    await entered;
    try{
      await expect(router.run({...binding,threadId:"b"},"second")).rejects.toThrow("Workspace already executing");
    }finally{finish();await failure;}
    send.mockResolvedValueOnce(undefined);
    await router.run({...binding,threadId:"b"},"third");
  });
});
