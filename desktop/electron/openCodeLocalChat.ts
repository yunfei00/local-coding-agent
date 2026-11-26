import {OpenCodeSupervisor} from "./openCodeSupervisor";
import {OpenCodeAdapter} from "./engineAdapter";
import {OpenCodeConversation} from "./openCodeConversation";
import {OpenCodeChat} from "./openCodeChat";
import {startLocalModelGateway} from "./localModelGateway";
import {acquireEngineLease} from "./engineLease";
import type {EngineEvent} from "./engineEventBridge";
import type {LocalModelProfile} from "./openCodeModelConfig";

// Isolated text-only diagnostic; not a production workspace execution route.
export async function runLocalChat(input:{binary:string;root:string;dataDir:string;profile:LocalModelProfile;ollamaPort:number;prompt:string;followup?:string;messages?:string[]},onText:(delta:string)=>void,signal:AbortSignal,onEvent?:(event:EngineEvent)=>void){
  const messages=input.messages??[input.prompt,...(input.followup?[input.followup]:[])];
  if(messages.length<1||messages.length>20||messages.some(message=>typeof message!=="string"||!message.trim()||Buffer.byteLength(message)>65536)||messages.reduce((sum,message)=>sum+Buffer.byteLength(message),0)>131072)throw new Error("Invalid conversation messages");
  signal.throwIfAborted();
  const release=await acquireEngineLease(input.dataDir);
  const supervisor=new OpenCodeSupervisor();
  let gateway:Awaited<ReturnType<typeof startLocalModelGateway>>|undefined;
  try{
    signal.throwIfAborted();
    gateway=await startLocalModelGateway(input.profile.model,input.ollamaPort,{requests:messages.length*4,inputBytes:262144,maxOutput:input.profile.maxOutput,durationMs:480000});
    await supervisor.start(input.binary,input.root,{profile:input.profile,gateway});
    signal.throwIfAborted();
    const adapter=new OpenCodeAdapter((route,method,body)=>supervisor.request(route,method,body));
    const id=await adapter.create(input.root,"P2 isolated text chat");
    const chat=new OpenCodeChat(supervisor);
    const conversation=new OpenCodeConversation(supervisor,id,(prompt,turnSignal)=>chat.run(id,prompt,onText,turnSignal,onEvent),20);
    try{
      for(let i=0;i<messages.length;i++){
        if(i>0)onText("\n\n--- 第 "+(i+1)+" 轮 ---\n\n");
        const result=await conversation.send(messages[i],signal);
        if(result.outcome!=="succeeded"||i===messages.length-1)return {sessionId:id,...result,usage:gateway.usage(),turns:conversation.turns};
      }
      throw new Error("Conversation did not execute");
    }finally{conversation.close();}
  }finally{
    // Close model transport first. Never release ownership if process cleanup fails.
    try{await gateway?.close();}
    finally{await supervisor.stop();}
    await release();
  }
}
