// One pending turn at a time; no automatic replay after interruption.
export class InteractiveTurnQueue{
 private waiter?:{resolve:(value:string|null)=>void;reject:(error:Error)=>void};
 private closed=false;
 private count=0;
 private bytes=0;
 constructor(private readonly maxTurns=20,private readonly maxBytes=131072){}
 next(signal:AbortSignal):Promise<string|null>{
  if(this.closed||this.count>=this.maxTurns)return Promise.resolve(null);
  if(this.waiter)throw new Error("Already waiting for a turn");
  signal.throwIfAborted();
  return new Promise((resolve,reject)=>{
   const abort=()=>{this.closed=true;this.waiter=undefined;reject(new Error("Conversation interrupted"));};
   signal.addEventListener("abort",abort,{once:true});
   this.waiter={resolve:value=>{signal.removeEventListener("abort",abort);resolve(value);},reject:error=>{signal.removeEventListener("abort",abort);reject(error);}};
  });
 }
 submit(message:string){
  if(this.closed||!this.waiter)throw new Error("Conversation is not waiting for input");
  const size=Buffer.byteLength(message);
  if(!message.trim()||size>65536||this.bytes+size>this.maxBytes||this.count>=this.maxTurns)throw new Error("Conversation input limit exceeded");
  this.count++;this.bytes+=size;
  const waiter=this.waiter;this.waiter=undefined;waiter.resolve(message);
 }
 close(){this.closed=true;const waiter=this.waiter;this.waiter=undefined;waiter?.resolve(null);}
}
