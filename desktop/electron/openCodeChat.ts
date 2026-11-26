import {readEngineEvents} from "./openCodeEvents";
import {EngineEventDeduper} from "./engineEventDeduper";
import {translateEngineEvent, type EngineEvent} from "./engineEventBridge";

export type ChatTransport = {
  request(route:string,method?:string,body?:unknown):Promise<unknown>;
  events(signal:AbortSignal):Promise<Response>;
};
export type ChatResult = {outcome:"succeeded"|"failed"|"interrupted"; verified:false};
export class OpenCodeChat {
  private active=false;
  constructor(private readonly transport:ChatTransport){}
  async run(id:string,prompt:string,onText:(delta:string)=>void,signal:AbortSignal,onEvent?:(event:EngineEvent)=>void):Promise<ChatResult>{
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
    let hasText=false;
    const deduper=new EngineEventDeduper();
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
          if(event?.data?.sessionID!==id || !deduper.accept(frame))continue;
          const translated=translateEngineEvent(frame,id);
          if(translated)onEvent?.(translated);
          if(event.type==="session.text.delta"){
            const delta=event.data.delta??event.data.text;
            if(typeof delta==="string"){hasText ||= !!delta.trim();onText(delta);}
          }
          const outcome=event.type?.match(/^session\.execution\.(succeeded|failed|interrupted)$/)?.[1] as ChatResult["outcome"]|undefined;
          if(outcome){
            admitted=false;
            return {outcome:outcome==="succeeded"&&!hasText?"failed":outcome,verified:false};
          }
        }
        throw new Error("Chat stream ended without terminal event");
      }finally{controller.abort();await stream.return(undefined);}
    }catch(error){
      if(admitted){
        try{
          await this.transport.request(route+"/interrupt","POST");
          // Interrupt admission is not proof of cancellation. Require both persisted
          // terminal state and absence from the active drain list.
          for(let attempt=0;attempt<10;attempt++){
            const snapshot=await this.transport.request(route) as {data?:{id?:string;outcome?:string}};
            const active=await this.transport.request("/api/session/active") as {data?:Record<string,unknown>};
            if(snapshot?.data?.id===id && snapshot.data.outcome==="interrupted" && active?.data && !Object.hasOwn(active.data,id))
              return {outcome:"interrupted",verified:false};
            if(attempt<9)await new Promise(resolve=>setTimeout(resolve,150));
          }
        }catch{throw new Error("Chat outcome unknown; interrupt or reconciliation failed; retain execution lease");}
        throw new Error("Chat outcome unknown; interruption requested; reconcile before releasing execution lease");
      }
      throw error;
    }finally{
      clearTimeout(timer);signal.removeEventListener("abort",abort);controller.abort();this.active=false;
    }
  }
}
