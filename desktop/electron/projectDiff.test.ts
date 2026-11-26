import {describe,it,expect} from "vitest";
import {mkdtemp,writeFile,mkdir,rm} from "node:fs/promises";
import {execFileSync} from "node:child_process";
import path from "node:path";
import os from "node:os";
import {readProjectDiff} from "./projectDiff";
describe("project diff",()=>{
 it("separates staged and unstaged edits, lists untracked files and rejects nested roots",async()=>{
  const root=await mkdtemp(path.join(os.tmpdir(),"lca-diff-"));
  const git=(...args:string[])=>execFileSync("git",args,{cwd:root,windowsHide:true});
  try{
   git("init","--quiet","--template=");
   await writeFile(path.join(root,"a.txt"),"first\n");git("add","a.txt");
   await writeFile(path.join(root,"a.txt"),"second\n");
   await writeFile(path.join(root,"new.txt"),"new\n");
   const result=await readProjectDiff(root);
   expect(result.staged).toContain("+first");
   expect(result.unstaged).toContain("+second");
   expect(result.status).toContain("?? new.txt");
   const nested=path.join(root,"nested");await mkdir(nested);
   await expect(readProjectDiff(nested)).rejects.toThrow("repository root");
  }finally{await rm(root,{recursive:true,force:true});}
 });
});
