import {afterEach,beforeEach,describe,it,expect,vi} from "vitest";
import {mkdtemp,mkdir,rm} from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import {ProjectEngineService} from "./projectEngineService";
import {EngineSessionStore} from "./engineSessionStore";
import {LegacyAdapter} from "./engineAdapter";
import {acquireEngineLease} from "./engineLease";

describe("project engine routing",()=>{
  let root:string,project:string,data:string;
  beforeEach(async()=>{root=await mkdtemp(path.join(os.tmpdir(),"lca-project-"));project=path.join(root,"project");data=path.join(root,"data");await mkdir(project);});
  afterEach(async()=>{await rm(root,{recursive:true,force:true});});
  function setup(){
    const create=vi.fn(async()=>"session");
    const send=vi.fn(async(_id:string,_prompt:string)=>{});
    const store=new EngineSessionStore(path.join(data,"sessions.json"));
    const service=new ProjectEngineService(store,new LegacyAdapter({create,send,status:async()=>null,cancel:async()=>null}),data);
    const input={threadId:"thread",projectRoot:project,engine:"legacy" as const,title:"test",prompt:"hello"};
    return {create,send,store,service,input};
  }
  it("blocks production OpenCode before creating any session",async()=>{
    const {service,input,create,send}=setup();
    await expect(service.run({...input,engine:"opencode"})).rejects.toThrow("gate closed");
    expect(create).not.toHaveBeenCalled();expect(send).not.toHaveBeenCalled();
  });
  it("reuses a persisted binding across service instances",async()=>{
    const a=setup();await a.service.run(a.input);
    const b=setup();await b.service.run(b.input);
    expect(b.create).not.toHaveBeenCalled();
    expect(b.send).toHaveBeenCalledWith("session","hello");
  });
  it("rejects contention without dispatching and permits a later retry",async()=>{
    const {service,input,send}=setup();
    const release=await acquireEngineLease(data);
    try{await expect(service.run(input)).rejects.toThrow();expect(send).not.toHaveBeenCalled();}
    finally{await release();}
    await service.run(input);
    expect(send).toHaveBeenCalledTimes(1);
  });
  it("retains the lease after an ambiguous dispatch failure",async()=>{
    const {service,input,send}=setup();
    send.mockRejectedValueOnce(new Error("transport lost"));
    await expect(service.run(input)).rejects.toThrow("transport lost");
    await expect(acquireEngineLease(data)).rejects.toThrow();
    await expect(service.run(input)).rejects.toThrow();
    expect(send).toHaveBeenCalledTimes(1);
  });
  it("rejects project changes for a bound thread",async()=>{
    const {service,input,send}=setup();await service.run(input);
    const other=path.join(root,"other");await mkdir(other);
    await expect(service.run({...input,projectRoot:other})).rejects.toThrow("mismatch");
    expect(send).toHaveBeenCalledTimes(1);
  });
});
