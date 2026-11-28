import {describe,it,expect} from "vitest";
import {mkdtemp,mkdir,rm} from "node:fs/promises";
import {tmpdir} from "node:os";
import path from "node:path";
import {WorkspaceEngineLock} from "./workspaceEngineLock";
describe("workspace engine lock",()=>{
  it("blocks overlapping roots across engines and releases idempotently",async()=>{
    const root=await mkdtemp(path.join(tmpdir(),"lca-lock-"));
    try{
      const a=path.join(root,"a"),b=path.join(root,"b"),nested=path.join(a,"nested");
      await mkdir(nested,{recursive:true});await mkdir(b);
      const lock=new WorkspaceEngineLock();
      const first=await lock.acquire(a,"legacy","t");
      await expect(lock.acquire(nested,"opencode","u")).rejects.toThrow("already executing");
      await expect(lock.acquire(root,"opencode","u")).rejects.toThrow("already executing");
      const other=await lock.acquire(b,"opencode","u");other.release();
      first.release();first.release();
      const next=await lock.acquire(nested,"opencode","u");
      first.release();
      await expect(lock.acquire(a,"legacy","t")).rejects.toThrow("already executing");
      next.release();
    }finally{await rm(root,{recursive:true,force:true});}
  });
  it("admits only one concurrent acquisition",async()=>{
    const root=await mkdtemp(path.join(tmpdir(),"lca-lock-"));
    try{
      const lock=new WorkspaceEngineLock();
      const results=await Promise.allSettled([lock.acquire(root,"legacy","a"),lock.acquire(root,"opencode","b")]);
      expect(results.filter(r=>r.status==="fulfilled")).toHaveLength(1);
      for(const r of results)if(r.status==="fulfilled")r.value.release();
    }finally{await rm(root,{recursive:true,force:true});}
  });
});
