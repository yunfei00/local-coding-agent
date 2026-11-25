import { realpath, stat } from "node:fs/promises";
import path from "node:path";
import type { EngineId } from "./engineAdapter";

export type WorkspaceLease = { release():void };
type Owner = {root:string;engine:EngineId;threadId:string};
export class WorkspaceEngineLock {
  private readonly owners=new Set<Owner>();
  async acquire(root:string,engine:EngineId,threadId:string):Promise<WorkspaceLease>{
    if(!path.isAbsolute(root)||!threadId||!["legacy","opencode"].includes(engine))throw new Error("Invalid workspace lock request");
    const resolved=await realpath(root);
    if(!(await stat(resolved)).isDirectory())throw new Error("Workspace must be a directory");
    const canonical=process.platform==="win32"?resolved.toLowerCase():resolved;
    const overlaps=(a:string,b:string)=>{
      const relative=path.relative(a,b);
      return relative==="" || (!path.isAbsolute(relative)&&relative!==".."&&!relative.startsWith(".."+path.sep));
    };
    for(const owner of this.owners){
      if(overlaps(owner.root,canonical)||overlaps(canonical,owner.root))throw new Error("Workspace already executing: "+owner.engine);
    }
    const owner={root:canonical,engine,threadId};
    this.owners.add(owner);
    return {release:()=>{this.owners.delete(owner);}};
  }
}
