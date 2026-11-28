import {summarizeToolEvent} from "./toolEventSummary";
import { readEngineEvents, type RawEngineEvent } from "./openCodeEvents";
import { EngineEventDeduper } from "./engineEventDeduper";
export type EngineEvent = {
  engine:"opencode"; sessionId:string;
  kind:"text"|"reasoning"|"followup-delivered"|"usage"|"tool"|"execution-ended"|"snapshot"|"disconnected"|"approval"|"diff";
  payload:unknown;
};
type RecordValue = Record<string,unknown>;
function record(value:unknown):RecordValue|undefined {
  return value!==null && typeof value==="object" && !Array.isArray(value) ? value as RecordValue : undefined;
}
export function translateEngineEvent(raw:RawEngineEvent,sessionId:string):EngineEvent|undefined {
  const event=record(raw.data), data=record(event?.data);
  if(!data || data.sessionID!==sessionId || typeof event?.type!=="string")return;
  const base={engine:"opencode" as const,sessionId};
  const type=event.type;
  if(type==="session.text.delta"){
    const delta=data.delta ?? data.text;
    if(typeof delta==="string")return {...base,kind:"text",payload:{delta,
      ...(typeof data.assistantMessageID === "string" ? {messageId:data.assistantMessageID} : {})}};
  }
  if(type==="session.reasoning.delta" && typeof data.delta === "string")
    return {...base,kind:"reasoning",payload:{delta:data.delta,messageId:data.assistantMessageID}};
  if(type==="session.inbox.delivered" && typeof data.inboxID === "string")
    return {...base,kind:"followup-delivered",payload:{id:data.inboxID}};
  if(type==="session.usage.updated")return {...base,kind:"usage",payload:{tokens:data.tokens}};
  if(type.startsWith("session.tool.") && !type.includes(".input.")){
    return {...base,kind:"tool",payload:summarizeToolEvent(type,data)};
  }
  if(type==="permission.asked" || type==="session.permission.asked" || type==="permission.request"){
    return {...base,kind:"approval",payload:{
      requestId: data.requestID ?? data.requestId ?? data.id,
      action: data.action ?? data.permission,
      resources: data.resources ?? data.patterns ?? [],
      message: data.message,
      metadata: data.metadata,
      source: data.source,
      save: data.save,
    }};
  }
  if(type==="session.diff" || type==="file.edited" || type==="session.file.edited"){
    return {...base,kind:"diff",payload:{type, diff: data.diff ?? data.files ?? data.changes ?? data}};
  }
  if(["session.execution.succeeded","session.execution.failed","session.execution.interrupted"].includes(type))
    return {...base,kind:"execution-ended",payload:{outcome:type.split(".").pop(),verified:false,error:data.error}};
  if(type==="session.error")
    return {...base,kind:"execution-ended",payload:{outcome:"failed",verified:false,error:data.error ?? data.message}};
}
export interface EventSource {
  events(signal:AbortSignal):Promise<Response>;
  request(route:string):Promise<unknown>;
}
export class EngineEventBridge {
  private running=false;
  constructor(private readonly source:EventSource,private readonly retries=3){}
  async follow(sessionId:string,signal:AbortSignal,emit:(event:EngineEvent)=>void):Promise<void>{
    if(this.running)throw new Error("Event bridge already running");
    if(!sessionId)throw new Error("Session required");
    this.running=true;
    const deduper=new EngineEventDeduper();
    const base={engine:"opencode" as const,sessionId};
    try{
      for(let attempt=0;attempt<=this.retries && !signal.aborted;attempt++){
        const connection=new AbortController();
        const combined=AbortSignal.any([signal,connection.signal]);
        try{
          const response=await this.source.events(combined);
          const snapshot=record(await this.source.request("/api/session/"+encodeURIComponent(sessionId)));
          const data=record(snapshot?.data);
          if(data?.id!==sessionId)throw new Error("Session snapshot mismatch");
          if(signal.aborted)return;
          emit({...base,kind:"snapshot",payload:{outcome:data.outcome,verified:false,reconciliationRequired:attempt>0}});
          for await(const raw of readEngineEvents(response)){
            if(signal.aborted)return;
            const event=translateEngineEvent(raw,sessionId);
            if(event && deduper.accept(raw))emit(event);
          }
          if(!signal.aborted)throw new Error("Event stream closed");
        }catch{
          if(signal.aborted)return;
          emit({...base,kind:"disconnected",payload:{attempt:attempt+1,requiresConfirmation:true}});
          if(attempt===this.retries)throw new Error("Event recovery exhausted");
        }finally{connection.abort();}
        await new Promise<void>(resolve=>{
          const done=()=>{clearTimeout(timer);signal.removeEventListener("abort",done);resolve();};
          const timer=setTimeout(done,Math.min(1000*2**attempt,8000));
          signal.addEventListener("abort",done,{once:true});
          if(signal.aborted)done();
        });
      }
    }finally{this.running=false;}
  }
}
