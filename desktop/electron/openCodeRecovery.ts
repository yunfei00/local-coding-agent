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
