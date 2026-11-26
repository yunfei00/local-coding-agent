import {afterEach,beforeEach,describe,it,expect} from "vitest";
import {mkdtemp,mkdir,writeFile,rm,symlink} from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import {searchProject} from "./projectSearch";
describe("bounded project search",()=>{
 let root:string,project:string;
 beforeEach(async()=>{root=await mkdtemp(path.join(os.tmpdir(),"lca-search-"));project=path.join(root,"project");await mkdir(project);});
 afterEach(async()=>{await rm(root,{recursive:true,force:true});});
 it("finds filenames and literal content with line numbers",async()=>{
  await writeFile(path.join(project,"Example.ts"),"first\nconst Value = '[abc]';\n");
  expect((await searchProject(project,"example","file")).hits).toEqual([{file:"Example.ts"}]);
  expect((await searchProject(project,"[ABC]","text")).hits).toEqual([{file:"Example.ts",line:2,text:"const Value = '[abc]';"}]);
 });
 it("skips sensitive files, binary files and dependency trees",async()=>{
  await mkdir(path.join(project,"node_modules"));
  await writeFile(path.join(project,"node_modules","a.js"),"needle");
  await writeFile(path.join(project,".env.local"),"needle");
  await writeFile(path.join(project,"binary"),Buffer.from("needle\0"));
  expect((await searchProject(project,"needle","text")).hits).toEqual([]);
 });
 it("does not traverse a directory junction outside the project",async()=>{
  const outside=path.join(root,"outside");await mkdir(outside);await writeFile(path.join(outside,"secret.txt"),"needle");
  await symlink(outside,path.join(project,"linked"),process.platform==="win32"?"junction":"dir");
  expect((await searchProject(project,"needle","text")).hits).toEqual([]);
 });
 it("caps matches and respects cancellation",async()=>{
  await writeFile(path.join(project,"many.txt"),"needle\n".repeat(300));
  const result=await searchProject(project,"needle","text");
  expect(result.hits).toHaveLength(200);expect(result.truncated).toBe(true);
  const controller=new AbortController();controller.abort();
  await expect(searchProject(project,"needle","text",controller.signal)).rejects.toThrow();
 });
});
