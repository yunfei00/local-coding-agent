import {realpath,stat} from "node:fs/promises";
import path from "node:path";
import type {AgentEngine,SessionBinding,EngineId} from "./engineAdapter";
import type {EngineSessionStore} from "./engineSessionStore";
import {acquireEngineLease} from "./engineLease";

export type ProjectEngineRequest={threadId:string;projectRoot:string;engine:EngineId;title:string;prompt:string};
// Main-process service. No renderer-controlled flag can authorize OpenCode.
// Until the production permission/budget gate is implemented, OpenCode is denied.
export class ProjectEngineService {
  private active=new Set<string>();
  constructor(private readonly store:EngineSessionStore,private readonly legacy:AgentEngine,private readonly dataDir:string){}
  async run(input:ProjectEngineRequest):Promise<SessionBinding>{
    if(input.engine!=="legacy")throw new Error("Production OpenCode gate closed");
    if(!input.threadId.trim()||!input.prompt.trim()||!path.isAbsolute(input.projectRoot))throw new Error("Invalid project request");
    if(this.active.has(input.threadId))throw new Error("Thread already active");
    this.active.add(input.threadId);
    try{
      const root=await realpath(input.projectRoot);
      if(!(await stat(root)).isDirectory())throw new Error("Project is not a directory");
      const release=await acquireEngineLease(this.dataDir);
      let admitted=false,terminal=false;
      try{
        let binding=await this.store.get(input.threadId);
        if(binding){
          if(binding.engine!==input.engine||binding.projectRoot!==root)throw new Error("Thread project or engine mismatch");
        }else{
          binding={threadId:input.threadId,engine:input.engine,projectRoot:root,sessionId:await this.legacy.create(root,input.title)};
          await this.store.bind(binding);
        }
        // Delegate must own the complete execution lifecycle and confirm cleanup.
        admitted=true;
        await this.legacy.send(binding.sessionId,input.prompt);
        terminal=true;
        return binding;
      }finally{if(!admitted||terminal)await release();}
    }finally{this.active.delete(input.threadId);}
  }
}
