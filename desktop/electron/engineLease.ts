import {mkdir,writeFile,readFile,unlink,rmdir,realpath} from "node:fs/promises";
import {randomUUID} from "node:crypto";
import path from "node:path";

// Same on-disk protocol as agent/core/engine_lease.py.
export async function acquireEngineLease(dataDir:string):Promise<()=>Promise<void>>{
  await mkdir(dataDir,{recursive:true});
  const lock=path.join(await realpath(dataDir),"engine-execution.lock");
  const owner=path.join(lock,"owner");
  const token=process.pid+":"+randomUUID().replace(/-/g,"");
  await mkdir(lock);
  await writeFile(owner,token,{flag:"wx",encoding:"ascii"});
  let released=false;
  return async()=>{
    if(released)return;
    if(await readFile(owner,"ascii")!==token)throw new Error("Engine lease ownership changed");
    await unlink(owner);
    await rmdir(lock);
    released=true;
  };
}
