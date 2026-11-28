import {lstat,realpath} from "node:fs/promises";
import path from "node:path";
export async function resolveRecoveryStorage(base:string,storageId:string):Promise<string>{
 if(!path.isAbsolute(base)||!/^opencode-chat-[A-Za-z0-9_-]{6,64}$/.test(storageId))throw new Error("Invalid recovery storage");
 const root=await realpath(base);
 const candidate=path.join(root,storageId);
 const stat=await lstat(candidate);
 if(!stat.isDirectory()||stat.isSymbolicLink())throw new Error("Invalid recovery directory");
 const resolved=await realpath(candidate);
 if(path.relative(root,resolved)!==storageId)throw new Error("Recovery directory mismatch");
 return resolved;
}
