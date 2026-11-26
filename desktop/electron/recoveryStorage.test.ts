import {describe,it,expect} from "vitest";
import {mkdtemp,mkdir,rm} from "node:fs/promises";
import path from "node:path";
import os from "node:os";
import {resolveRecoveryStorage} from "./recoveryStorage";
describe("recovery storage",()=>{
 it("accepts only existing isolated child directories",async()=>{
  const root=await mkdtemp(path.join(os.tmpdir(),"lca-recovery-"));
  try{
   const id="opencode-chat-abcdef";
   await mkdir(path.join(root,id));
   expect(path.basename(await resolveRecoveryStorage(root,id))).toBe(id);
   await expect(resolveRecoveryStorage(root,"../outside")).rejects.toThrow("Invalid");
   await expect(resolveRecoveryStorage(root,"opencode-chat-missing")).rejects.toThrow();
  }finally{await rm(root,{recursive:true,force:true});}
 });
});
