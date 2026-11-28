import { describe, expect, it } from "vitest";
import { mkdtemp, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";
import { EngineSessionStore } from "./engineSessionStore";
import { readEngineEvents } from "./openCodeEvents";

describe("P1 isolated infrastructure",()=>{
  it("persists immutable bindings across store instances",async()=>{
    const root=await mkdtemp(path.join(tmpdir(),"lca-engine-"));
    try{
      const file=path.join(root,"bindings.json");
      const store=new EngineSessionStore(file);
      const binding={threadId:"t",engine:"legacy" as const,sessionId:"s",projectRoot:root};
      await store.bind(binding);
      await store.bind(binding);
      expect(await new EngineSessionStore(file).get("t")).toEqual(binding);
      await expect(store.bind({...binding,engine:"opencode"})).rejects.toThrow("immutable");
      await Promise.all([store.bind({...binding,threadId:"a"}),store.bind({...binding,threadId:"b"})]);
      expect(await store.get("a")).toBeDefined();
      expect(await store.get("b")).toBeDefined();
      await writeFile(file,"invalid");
      await expect(store.get("t")).rejects.toThrow();
    }finally{await rm(root,{recursive:true,force:true});}
  });
  it("parses split UTF-8 SSE frames",async()=>{
    const bytes=new TextEncoder().encode('id: 1\r\nevent: update\r\ndata: {"text":"中文"}\r\n\r\n: ping\n\ndata: {"done":true}\n\n');
    const response=new Response(new ReadableStream({start(controller){for(const byte of bytes)controller.enqueue(Uint8Array.of(byte));controller.close();}}));
    const events=[];
    for await(const event of readEngineEvents(response))events.push(event);
    expect(events).toEqual([{id:"1",event:"update",data:{text:"中文"}},{id:undefined,event:undefined,data:{done:true}}]);
  });
  it("rejects truncated frames",async()=>{
    const consume=async()=>{for await(const _ of readEngineEvents(new Response('data: {"x":1}'))){}};
    await expect(consume()).rejects.toThrow("Incomplete");
  });
});
