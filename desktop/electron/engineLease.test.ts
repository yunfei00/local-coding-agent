import {describe,it,expect} from "vitest";
import {mkdtemp,rm,mkdir} from "node:fs/promises";
import {tmpdir} from "node:os";
import path from "node:path";
import {acquireEngineLease} from "./engineLease";

describe("shared engine lease",()=>{
  it("excludes competing owners and permits acquisition after release",async()=>{
    const root=await mkdtemp(path.join(tmpdir(),"lca-lease-"));
    try{
      const release=await acquireEngineLease(root);
      try{await expect(acquireEngineLease(root)).rejects.toThrow();}
      finally{await release();}
      await release();
      const next=await acquireEngineLease(root);
      await next();
    }finally{await rm(root,{recursive:true,force:true});}
  });
  it("does not reclaim an incomplete or orphaned lock",async()=>{
    const root=await mkdtemp(path.join(tmpdir(),"lca-lease-"));
    try{
      await mkdir(path.join(root,"engine-execution.lock"));
      await expect(acquireEngineLease(root)).rejects.toThrow();
    }finally{await rm(root,{recursive:true,force:true});}
  });
});
