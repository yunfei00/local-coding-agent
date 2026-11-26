import {OpenCodeSupervisor} from "./openCodeSupervisor";
import {OpenCodeAdapter} from "./engineAdapter";
import {OpenCodeChat} from "./openCodeChat";
import {startLocalModelGateway} from "./localModelGateway";
import {acquireEngineLease} from "./engineLease";
import type {LocalModelProfile} from "./openCodeModelConfig";

// Isolated text-only diagnostic; not a production workspace execution route.
export async function runLocalChat(input:{binary:string;root:string;dataDir:string;profile:LocalModelProfile;ollamaPort:number;prompt:string},onText:(delta:string)=>void,signal:AbortSignal){
  signal.throwIfAborted();
  const release=await acquireEngineLease(input.dataDir);
  const supervisor=new OpenCodeSupervisor();
  let gateway:Awaited<ReturnType<typeof startLocalModelGateway>>|undefined;
  try{
    signal.throwIfAborted();
    gateway=await startLocalModelGateway(input.profile.model,input.ollamaPort,{requests:4,inputBytes:262144,maxOutput:input.profile.maxOutput,durationMs:480000});
    await supervisor.start(input.binary,input.root,{profile:input.profile,gateway});
    signal.throwIfAborted();
    const adapter=new OpenCodeAdapter((route,method,body)=>supervisor.request(route,method,body));
    const id=await adapter.create(input.root,"P2 isolated text chat");
    const result=await new OpenCodeChat(supervisor).run(id,input.prompt,onText,signal);
    return {sessionId:id,...result,usage:gateway.usage()};
  }finally{
    // Close model transport first. Never release ownership if process cleanup fails.
    try{await gateway?.close();}
    finally{await supervisor.stop();}
    await release();
  }
}
