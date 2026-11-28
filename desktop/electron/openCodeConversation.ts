import type {ChatResult} from "./openCodeChat";
export interface ConversationTransport {
 request(route:string):Promise<unknown>;
}
export class OpenCodeConversation {
 private busy=false;
 private closed=false;
 private count=0;
 constructor(private readonly transport:ConversationTransport,private readonly sessionId:string,private readonly execute:(prompt:string,signal:AbortSignal)=>Promise<ChatResult>,private readonly maxTurns=20){
  if(!/^[A-Za-z0-9_-]+$/.test(sessionId)||!Number.isSafeInteger(maxTurns)||maxTurns<1||maxTurns>100)throw new Error("Invalid conversation configuration");
 }
 get turns(){return this.count;}
 close(){this.closed=true;}
 async send(prompt:string,signal:AbortSignal):Promise<ChatResult>{
  if(this.closed||this.busy||this.count>=this.maxTurns)throw new Error("Conversation unavailable");
  if(!prompt.trim()||Buffer.byteLength(prompt)>65536)throw new Error("Invalid prompt");
  signal.throwIfAborted();this.busy=true;
  try{
   let idle=false;
   for(let i=0;i<30;i++){
    signal.throwIfAborted();
    const reply=await this.transport.request("/api/session/active") as {data?:unknown};
    const data=reply?.data;
    if(data&&typeof data==="object"&&!Array.isArray(data)&&!Object.hasOwn(data,this.sessionId)){idle=true;break;}
    await new Promise(resolve=>setTimeout(resolve,100));
   }
   if(!idle)throw new Error("Session drain not confirmed idle");
   signal.throwIfAborted();
   this.count++;
   const result=await this.execute(prompt,signal);
   if(result.outcome!=="succeeded")this.close();
   return result;
  }catch(error){this.close();throw error;}
  finally{this.busy=false;}
 }
}
