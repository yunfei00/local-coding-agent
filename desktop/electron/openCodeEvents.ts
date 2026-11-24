export type RawEngineEvent = {id?:string; event?:string; data:unknown};
// No event type is inferred from model text. Reconnection requires snapshot reconciliation.
export async function* readEngineEvents(response:Response):AsyncGenerator<RawEngineEvent>{
  if(!response.body)throw new Error("Missing event stream");
  const reader=response.body.getReader();
  const decoder=new TextDecoder();
  let pending="";
  try{
    while(true){
      const {done,value}=await reader.read();
      if(done)break;
      pending+=decoder.decode(value,{stream:true});
      let boundary:RegExpMatchArray|null;
      while((boundary=pending.match(/\r?\n\r?\n/))!==null){
        const index=boundary.index!;
        const frame=pending.slice(0,index);pending=pending.slice(index+boundary[0].length);
        if(frame.length>1024*1024)throw new Error("Oversized SSE frame");
        let id:string|undefined,event:string|undefined;const data:string[]=[];
        for(const line of frame.split(/\r?\n/)){
          if(line.startsWith("id:"))id=line.slice(3).trim();
          else if(line.startsWith("event:"))event=line.slice(6).trim();
          else if(line.startsWith("data:"))data.push(line.slice(5).replace(/^ /,""));
        }
        if(data.length)yield {id,event,data:JSON.parse(data.join("\n"))};
      }
      if(pending.length>1024*1024)throw new Error("Oversized SSE buffer");
    }
    if(pending.trim())throw new Error("Incomplete SSE frame");
  } finally {await reader.cancel().catch(()=>{});reader.releaseLock();}
}
