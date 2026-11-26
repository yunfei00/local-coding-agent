import {readEngineEvents} from "./openCodeEvents";

export type ChatTransport = {
  request(route:string,method?:string,body?:unknown):Promise<unknown>;
  events(signal:AbortSignal):Promise<Response>;
};
export type ChatResult = {outcome:"succeeded"|"failed"|"interrupted"; verified:false};
export class OpenCodeChat {
  private active=false;
  constructor(private readonly transport:ChatTransport){}
  async run(id:string,prompt:string,onText:(delta:string)=>void,signal:AbortSignal):Promise<ChatResult>{
    if(this.active)throw new Error("Chat already active");
    if(!/^[A-Za-z0-9_-]+$/.test(id)||!prompt.trim()||Buffer.byteLength(prompt)>65536)throw new Error("Invalid chat input");
    signal.throwIfAborted();
    this.active=true;
    const controller=new AbortController();
    const abort=()=>controller.abort();
    signal.addEventListener("abort",abort,{once:true});
    const timer=setTimeout(abort,480000);
    const route="/api/session/"+id;
    let admitted=false;
    try{
      const response=await this.transport.events(controller.signal);
      const stream=readEngineEvents(response);
      try{
        controller.signal.throwIfAborted();
        // Admission may have reached the server even if the HTTP response is lost.
        admitted=true;
        await this.transport.request(route+"/prompt","POST",{text:prompt});
        for await(const frame of stream){
          controller.signal.throwIfAborted();
          const event=frame.data as {type?:string;data?:{sessionID?:string;delta?:string;text?:string}};
          if(event?.data?.sessionID!==id)continue;
          if(event.type==="session.text.delta"){
            const delta=event.data.delta??event.data.text;
            if(typeof delta==="string")onText(delta);
          }
          const outcome=event.type?.match(/^session\.execution\.(succeeded|failed|interrupted)$/)?.[1] as ChatResult["outcome"]|undefined;
          if(outcome){
            admitted=false;
            return {outcome,verified:false};
          }
        }
        throw new Error("Chat stream ended without terminal event");
      }finally{controller.abort();await stream.return(undefined);}
    }catch(error){
      if(admitted){
        try{await this.transport.request(route+"/interrupt","POST");}
        catch{throw new Error("Chat outcome unknown; interrupt failed; retain execution lease");}
        throw new Error("Chat outcome unknown; interruption requested; reconcile before releasing execution lease");
      }
      throw error;
    }finally{
      clearTimeout(timer);signal.removeEventListener("abort",abort);controller.abort();this.active=false;
    }
  }
}
