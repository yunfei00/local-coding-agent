import {describe,it,expect,vi} from "vitest";
import {OpenCodeChat} from "./openCodeChat";
function response(events:unknown[]){
  return new Response(events.map(e=>"data: "+JSON.stringify(e)+"\n\n").join(""));
}
describe("P2 chat streaming",()=>{
  it("filters unrelated sessions and waits for terminal execution",async()=>{
    const request=vi.fn(async()=>({}));
    const chat=new OpenCodeChat({request,events:async()=>response([
      {type:"session.text.delta",data:{sessionID:"other",delta:"wrong"}},
      {type:"session.text.delta",data:{sessionID:"s1",delta:"hello"}},
      {type:"session.execution.succeeded",data:{sessionID:"s1"}}
    ])});
    const output:string[]=[];
    expect(await chat.run("s1","hello",s=>output.push(s),new AbortController().signal)).toEqual({outcome:"succeeded",verified:false});
    expect(output).toEqual(["hello"]);
    expect(request).toHaveBeenCalledWith("/api/session/s1/prompt","POST",{text:"hello"});
  });
  it("does not claim completion after a truncated stream",async()=>{
    const request=vi.fn(async()=>({}));
    const chat=new OpenCodeChat({request,events:async()=>response([])});
    await expect(chat.run("s1","hello",()=>{},new AbortController().signal)).rejects.toThrow("outcome unknown");
    expect(request).toHaveBeenCalledWith("/api/session/s1/interrupt","POST");
  });
  it("rejects invalid session IDs before transport access",async()=>{
    const request=vi.fn(async()=>({}));
    const chat=new OpenCodeChat({request,events:async()=>response([])});
    await expect(chat.run("../s1","hello",()=>{},new AbortController().signal)).rejects.toThrow("Invalid chat input");
    expect(request).not.toHaveBeenCalled();
  });
  it("rejects terminal success without a visible response",async()=>{
    const request=vi.fn(async()=>({}));
    const chat=new OpenCodeChat({request,events:async()=>response([{type:"session.execution.succeeded",data:{sessionID:"s1"}}])});
    expect(await chat.run("s1","hello",()=>{},new AbortController().signal)).toEqual({outcome:"failed",verified:false});
  });
  it("reports interrupted only after persisted and inactive reconciliation",async()=>{
    const request=vi.fn(async(route:string)=>{
      if(route==="/api/session/s1")return {data:{id:"s1",outcome:"interrupted"}};
      if(route==="/api/session/active")return {data:{}};
      return {};
    });
    const chat=new OpenCodeChat({request,events:async()=>response([])});
    expect(await chat.run("s1","hello",()=>{},new AbortController().signal)).toEqual({outcome:"interrupted",verified:false});
  });
  it("deduplicates explicit SSE event IDs and reports execution events",async()=>{
    const request=vi.fn(async()=>({}));
    const delta={type:"session.text.delta",data:{sessionID:"s1",delta:"hello"}};
    const feed=new Response("id: d1\ndata: "+JSON.stringify(delta)+"\n\nid: d1\ndata: "+JSON.stringify(delta)+"\n\ndata: "+JSON.stringify({type:"session.execution.succeeded",data:{sessionID:"s1"}})+"\n\n");
    const chat=new OpenCodeChat({request,events:async()=>feed});
    const output:string[]=[];
    const emit=vi.fn();
    expect(await chat.run("s1","hello",s=>output.push(s),new AbortController().signal,emit)).toEqual({outcome:"succeeded",verified:false});
    expect(output).toEqual(["hello"]);
    expect(emit).toHaveBeenCalledTimes(2);
  });
});
