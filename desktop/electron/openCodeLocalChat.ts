import {OpenCodeSupervisor} from "./openCodeSupervisor";
import {OpenCodeAdapter} from "./engineAdapter";
import {OpenCodeChat} from "./openCodeChat";
import {startLocalModelGateway} from "./localModelGateway";
import {acquireEngineLease} from "./engineLease";
import type {EngineEvent} from "./engineEventBridge";
import type {LocalModelProfile} from "./openCodeModelConfig";

// Isolated text-only diagnostic; not a production workspace execution route.
export async function runLocalChat(input:{binary:string;root:string;dataDir:string;profile:LocalModelProfile;ollamaPort:number;prompt:string;followup?:string},onText:(delta:string)=>void,signal:AbortSignal,onEvent?:(event:EngineEvent)=>void){
  signal.throwIfAborted();
  const release=await acquireEngineLease(input.dataDir);
  const supervisor=new OpenCodeSupervisor();
  let gateway:Awaited<ReturnType<typeof startLocalModelGateway>>|undefined;
  try{
    signal.throwIfAborted();
    gateway=await startLocalModelGateway(input.profile.model,input.ollamaPort,{requests:input.followup?8:4,inputBytes:262144,maxOutput:input.profile.maxOutput,durationMs:480000});
    await supervisor.start(input.binary,input.root,{profile:input.profile,gateway});
    signal.throwIfAborted();
    const adapter=new OpenCodeAdapter((route,method,body)=>supervisor.request(route,method,body));
    const id=await adapter.create(input.root,"P2 isolated text chat");
    const chat=new OpenCodeChat(supervisor);
    const first=await chat.run(id,input.prompt,onText,signal,onEvent);
    if(first.outcome!=="succeeded"||!input.followup)return {sessionId:id,...first,usage:gateway.usage(),turns:1};
    let idle=false;
    for(let i=0;i<30;i++){
      signal.throwIfAborted();
      const active=await supervisor.request("/api/session/active") as {data?:Record<string,unknown>};
      if(active?.data && !Object.hasOwn(active.data,id)){idle=true;break;}
      await new Promise(resolve=>setTimeout(resolve,100));
    }
    if(!idle)throw new Error("Session drain not confirmed idle; follow-up not submitted");
    onText("\n\n--- 第二轮 ---\n\n");
    const result=await chat.run(id,input.followup,onText,signal,onEvent);
    return {sessionId:id,...result,usage:gateway.usage(),turns:2};
  }finally{
    // Close model transport first. Never release ownership if process cleanup fails.
    try{await gateway?.close();}
    finally{await supervisor.stop();}
    await release();
  }
}
