import {describe,it,expect} from "vitest";
import {mkdtemp,rm} from "node:fs/promises";
import {tmpdir} from "node:os";
import path from "node:path";
import {spawnSync} from "node:child_process";
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
});
