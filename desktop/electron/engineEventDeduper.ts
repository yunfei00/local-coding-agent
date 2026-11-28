import type { RawEngineEvent } from "./openCodeEvents";

// Only explicit transport IDs are safe to deduplicate. Reset after snapshot reconciliation.
export class EngineEventDeduper {
  private readonly seen=new Set<string>();
  constructor(private readonly capacity=4096){
    if(!Number.isSafeInteger(capacity)||capacity<1)throw new Error("Invalid event capacity");
  }
  accept(event:RawEngineEvent):boolean{
    if(!event.id)return true;
    if(this.seen.has(event.id))return false;
    this.seen.add(event.id);
    if(this.seen.size>this.capacity){
      const oldest=this.seen.values().next().value;
      if(oldest!==undefined)this.seen.delete(oldest);
    }
    return true;
  }
  reset():void{this.seen.clear();}
}
