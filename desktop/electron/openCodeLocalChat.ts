import {writeFile,mkdtemp} from "node:fs/promises";
import path from "node:path";
import {execFileSync} from "node:child_process";
import {OpenCodeSupervisor} from "./openCodeSupervisor";
import {OpenCodeAdapter} from "./engineAdapter";
import {OpenCodeConversation} from "./openCodeConversation";
import {OpenCodeChat} from "./openCodeChat";
import {startLocalModelGateway} from "./localModelGateway";
import {acquireEngineLease} from "./engineLease";
import type {EngineEvent} from "./engineEventBridge";
import type {LocalModelProfile} from "./openCodeModelConfig";

// Isolated text-only diagnostic; not a production workspace execution route.
export async function runLocalChat(input:{binary:string;root:string;dataDir:string;profile:LocalModelProfile;ollamaPort:number;ollamaBaseUrl?:string;prompt:string;followup?:string;messages?:string[];fixtureTools?:boolean},onText:(delta:string)=>void,signal:AbortSignal,onEvent?:(event:EngineEvent)=>void,nextTurn?:(signal:AbortSignal)=>Promise<string|null>,onSession?:(id:string)=>Promise<void>){
  const messages=[...(input.messages??[input.prompt,...(input.followup?[input.followup]:[])])];
  if(messages.length<1||messages.length>20||messages.some(message=>typeof message!=="string"||!message.trim()||Buffer.byteLength(message)>65536)||messages.reduce((sum,message)=>sum+Buffer.byteLength(message),0)>131072)throw new Error("Invalid conversation messages");
  signal.throwIfAborted();
  const release=await acquireEngineLease(input.dataDir);
  const supervisor=new OpenCodeSupervisor();
  let gateway:Awaited<ReturnType<typeof startLocalModelGateway>>|undefined;
  try{
    signal.throwIfAborted();
    const root=input.fixtureTools?await mkdtemp(path.join(input.root,"fixture-")):input.root;
    if(input.fixtureTools){
      await writeFile(path.join(root,"seed.txt"),"P2_FIXTURE",{flag:"wx"});
      await writeFile(path.join(root,"add.cjs"),"module.exports = (a, b) => a - b;\n",{flag:"wx"});
      execFileSync("git",["init","--quiet","--template="],{cwd:root,timeout:10000,windowsHide:true});
      execFileSync("git",["add","--","seed.txt","add.cjs"],{cwd:root,timeout:10000,windowsHide:true});
    }
    gateway=await startLocalModelGateway(input.profile.model,input.ollamaPort,{upstreamBaseUrl:input.ollamaBaseUrl,allowTools:input.fixtureTools===true,requests:input.fixtureTools?28:nextTurn?80:messages.length*4,inputBytes:262144,maxOutput:input.profile.maxOutput,durationMs:480000});
    await supervisor.start(input.binary,root,{profile:input.profile,gateway,fixtureTools:input.fixtureTools});
    signal.throwIfAborted();
    const adapter=new OpenCodeAdapter((route,method,body)=>supervisor.request(route,method,body));
    const id=await adapter.create(root,input.fixtureTools?"P2 fixture agent":"P2 isolated text chat");
    await onSession?.(id);
    const chat=new OpenCodeChat(supervisor);
    const conversation=new OpenCodeConversation(supervisor,id,(prompt,turnSignal)=>chat.run(id,prompt,onText,turnSignal,onEvent,input.fixtureTools?"tool-or-text":"text"),20);
    try{
      let totalBytes=messages.reduce((sum,message)=>sum+Buffer.byteLength(message),0);
      const deadline=Date.now()+480000;
      for(let i=0;i<messages.length;i++){
        if(i>0)onText("\n\n--- 第 "+(i+1)+" 轮 ---\n\n");
        const result=await conversation.send(messages[i],signal);
        if(result.outcome==="succeeded"&&i===messages.length-1&&nextTurn&&messages.length<20){
          const waitSignal=AbortSignal.any([signal,AbortSignal.timeout(Math.max(1,deadline-Date.now()))]);
          const next=await nextTurn(waitSignal);
          if(next!==null){
            totalBytes+=Buffer.byteLength(next);
            if(!next.trim()||Buffer.byteLength(next)>65536||totalBytes>131072)throw new Error("Conversation input limit exceeded");
            messages.push(next);
          }
        }
        if(result.outcome!=="succeeded"||i===messages.length-1)return {fixtureRoot:input.fixtureTools?root:undefined,sessionId:id,...result,usage:gateway.usage(),turns:conversation.turns};
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
