import {describe,it,expect} from "vitest";
import {mkdtemp,rm} from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import {OpenCodeHistory} from "./openCodeHistory";
describe("OpenCode history",()=>{
 it("persists completed conversations and marks unfinished runs unknown",async()=>{
  const dir=await mkdtemp(path.join(os.tmpdir(),"lca-history-"));
  try{
   const file=path.join(dir,"history.json"),first=new OpenCodeHistory(file);
   const id=await first.begin("model",["hello"]);
   await first.finish(id,"succeeded","reply","session");
   const unfinished=await first.begin("model",["next"]);
   await first.bindSession(unfinished,"original-session");
   await expect(first.bindSession(unfinished,"different")).rejects.toThrow("binding");
   await first.checkpoint(unfinished,"partial reply","follow-up");
   const second=new OpenCodeHistory(file);await second.recover();
   const rows=await second.list();
   expect(rows.find(r=>r.id===id)).toMatchObject({status:"succeeded",output:"reply",sessionId:"session"});
   expect(rows.find(r=>r.id===unfinished)).toMatchObject({status:"unknown",sessionId:"original-session",messages:["next","follow-up"],output:"partial reply"});
   await expect(second.finish(id,"failed","")).rejects.toThrow("terminal");
  }finally{await rm(dir,{recursive:true,force:true});}
 });
});
