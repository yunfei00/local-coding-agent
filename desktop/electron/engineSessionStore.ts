import { mkdir, readFile, rename, writeFile, unlink } from "node:fs/promises";
import { randomUUID } from "node:crypto";
import path from "node:path";
import type { SessionBinding } from "./engineAdapter";

// Main-process-only store; single writer. Existing thread bindings are immutable.
export class EngineSessionStore {
  private queue: Promise<unknown> = Promise.resolve();
  constructor(private readonly file: string) {}
  private async read(): Promise<SessionBinding[]> {
    try {
      const value:unknown=JSON.parse(await readFile(this.file,"utf8"));
      if(!Array.isArray(value))throw new Error("Invalid engine session store");
      const ids=new Set<string>();
      for(const item of value){
        if(!item || typeof item.threadId!=="string" || !item.threadId || ids.has(item.threadId) ||
          !["legacy","opencode"].includes(item.engine) || typeof item.sessionId!=="string" || !item.sessionId ||
          typeof item.projectRoot!=="string" || !path.isAbsolute(item.projectRoot))throw new Error("Invalid engine binding");
        ids.add(item.threadId);
      }
      return value;
    } catch(error){if((error as NodeJS.ErrnoException).code==="ENOENT")return [];throw error;}
  }
  async get(threadId:string):Promise<SessionBinding|undefined>{await this.queue;return (await this.read()).find(item=>item.threadId===threadId);}
  bind(binding:SessionBinding):Promise<void>{
    const snapshot={...binding};
    const task=this.queue.then(async()=>{
      if(!snapshot.threadId || !snapshot.sessionId || !path.isAbsolute(snapshot.projectRoot) || !["legacy","opencode"].includes(snapshot.engine))throw new Error("Invalid binding");
      const rows=await this.read();
      const previous=rows.find(item=>item.threadId===snapshot.threadId);
      if(previous){if(previous.engine!==snapshot.engine || previous.sessionId!==snapshot.sessionId || previous.projectRoot!==snapshot.projectRoot)throw new Error("Thread engine binding is immutable");return;}
      await mkdir(path.dirname(this.file),{recursive:true});
      const temporary=this.file+"."+randomUUID()+".tmp";
      try{await writeFile(temporary,JSON.stringify([...rows,snapshot]),{flag:"wx",mode:0o600});await rename(temporary,this.file);}
      finally{await unlink(temporary).catch(()=>{});}
    });
    this.queue=task.catch(()=>{});
    return task;
  }
}
