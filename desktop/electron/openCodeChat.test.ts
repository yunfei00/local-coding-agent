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
});
