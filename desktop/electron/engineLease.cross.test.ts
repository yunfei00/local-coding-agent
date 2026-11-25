import {describe,it,expect} from "vitest";
import {mkdtemp,rm} from "node:fs/promises";
import {tmpdir} from "node:os";
import path from "node:path";
import {spawn,spawnSync} from "node:child_process";
import {acquireEngineLease} from "./engineLease";

describe("Python / Electron lease interoperability",()=>{
  it("Python rejects Electron ownership and acquires after release",async()=>{
    const root=await mkdtemp(path.join(tmpdir(),"lca-cross-"));
    const repo=path.resolve(__dirname,"../..");
    const python=process.env.LCA_TEST_PYTHON || (process.platform==="win32"?"python":"python3");
    const run=()=>spawnSync(python,["-c","import sys; from agent.core.engine_lease import engine_lease\nwith engine_lease(sys.argv[1]): print('acquired')",root],{cwd:repo,encoding:"utf8",timeout:10000});
    try{
      const release=await acquireEngineLease(root);
      try{
        const blocked=run();
        expect(blocked.error).toBeUndefined();
        expect(blocked.status).not.toBe(0);
        expect(blocked.stderr).toContain("Engine execution lease occupied");
      }finally{await release();}
      const allowed=run();
      expect(allowed.error).toBeUndefined();
      expect(allowed.status).toBe(0);
      expect(allowed.stdout).toContain("acquired");
    }finally{await rm(root,{recursive:true,force:true});}
  },30000);
  it("Electron rejects a live Python owner",async()=>{
    const root=await mkdtemp(path.join(tmpdir(),"lca-cross-reverse-"));
    const python=process.env.LCA_TEST_PYTHON || (process.platform==="win32"?"python":"python3");
    const child=spawn(python,["-u","-c","import sys; from agent.core.engine_lease import engine_lease\nwith engine_lease(sys.argv[1]):\n print('ready',flush=True)\n sys.stdin.readline()",root],{cwd:path.resolve(__dirname,"../.."),stdio:["pipe","pipe","pipe"]});
    const closed=new Promise<number|null>(resolve=>child.once("close",resolve));
    try{
      await new Promise<void>((resolve,reject)=>{
        const timer=setTimeout(()=>reject(new Error("Python lease readiness timeout")),10000);
        let output="";
        child.stdout.on("data",chunk=>{output+=String(chunk);if(output.includes("ready")){clearTimeout(timer);resolve();}});
        child.once("error",error=>{clearTimeout(timer);reject(error);});
        child.once("close",()=>{clearTimeout(timer);reject(new Error("Python exited before readiness"));});
      });
      await expect(acquireEngineLease(root)).rejects.toThrow();
      child.stdin.end("\n");
      expect(await closed).toBe(0);
      const release=await acquireEngineLease(root);
      await release();
    }finally{
      if(child.exitCode===null && child.signalCode===null)child.kill();
      await closed;
      await rm(root,{recursive:true,force:true});
    }
  },30000);
});
