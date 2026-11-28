type Transport={request(route:string):Promise<unknown>};
function record(value:unknown):Record<string,unknown>{
 if(!value||typeof value!=="object"||Array.isArray(value))throw new Error("Invalid recovery response");
 return value as Record<string,unknown>;
}
export async function inspectOriginalSession(source:Transport,id:string){
 if(!/^[A-Za-z0-9_-]{1,128}$/.test(id))throw new Error("Invalid session ID");
 const snapshot=record(record(await source.request("/api/session/"+id)).data);
 if(snapshot.id!==id)throw new Error("Session identity mismatch");
 const active=record(await source.request("/api/session/active"));
 const outcome=typeof snapshot.outcome==="string"?snapshot.outcome:"unknown";
 return {sessionId:id,outcome,active:Object.prototype.hasOwnProperty.call(active,id),verified:false as const,canResume:false as const,requiresConfirmation:true as const};
}

export function recoverCompletedExchange(context:unknown, messageId:string, appended: ReadonlySet<string> = new Set()) {
  const messages = record(context).data;
  if (!Array.isArray(messages) || messages.length > 10000) return;
  const start = messages.findIndex(message=>message?.type === "user" && message.id === messageId);
  if (start < 0) return;
  let text = "";
  for (const message of messages.slice(start + 1)) {
    if (message?.type === "user" && !appended.has(message.id)) return;
    if (message?.type === "idle") {
      const outcome = message.outcome;
      if (outcome === "succeeded" || outcome === "failed" || outcome === "interrupted") return {outcome,text};
      return;
    }
    if (message?.type !== "assistant" || !Array.isArray(message.content)) continue;
    for (const part of message.content) {
      if (part?.type === "text" && typeof part.text === "string") text += part.text;
      if (text.length > 200000) return;
    }
  }
}
