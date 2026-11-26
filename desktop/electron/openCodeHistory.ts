import {mkdir,readFile,writeFile,rename,unlink} from "node:fs/promises";
import {randomUUID} from "node:crypto";
import path from "node:path";
export type HistoryEntry={id:string;model:string;createdAt:string;messages:string[];output:string;status:"running"|"succeeded"|"failed"|"interrupted"|"unknown";sessionId?:string};
export class OpenCodeHistory {
 private queue:Promise<unknown>=Promise.resolve();
 constructor(private readonly file:string){}
 private async read():Promise<HistoryEntry[]>{
  try{
   const raw=await readFile(this.file,"utf8");
   if(Buffer.byteLength(raw)>32*1024*1024)throw new Error("History exceeds limit");
   const rows=JSON.parse(raw);
   if(!Array.isArray(rows)||rows.length>100||rows.some(r=>!r||typeof r.id!=="string"||typeof r.model!=="string"||typeof r.createdAt!=="string"||!Array.isArray(r.messages)||r.messages.some((m:unknown)=>typeof m!=="string")||typeof r.output!=="string"||!["running","succeeded","failed","interrupted","unknown"].includes(r.status)))throw new Error("Invalid history");
   return rows;
  }catch(e){if((e as NodeJS.ErrnoException).code==="ENOENT")return [];throw e;}
 }
 private change(fn:(rows:HistoryEntry[])=>HistoryEntry[]):Promise<void>{
  const task=this.queue.then(async()=>{
   const rows=fn(await this.read());
   const raw=JSON.stringify(rows);
   if(Buffer.byteLength(raw)>32*1024*1024)throw new Error("History exceeds limit");
   await mkdir(path.dirname(this.file),{recursive:true});
   const tmp=this.file+"."+randomUUID()+".tmp";
   try{await writeFile(tmp,raw,{flag:"wx",mode:0o600});await rename(tmp,this.file);}
   finally{await unlink(tmp).catch(()=>{});}
  });
  this.queue=task.catch(()=>{});return task;
 }
 async list(){await this.queue;return this.read();}
 async begin(model:string,messages:string[]):Promise<string>{
  if(!model||messages.length<1||messages.length>20||messages.some(m=>typeof m!=="string")||Buffer.byteLength(JSON.stringify(messages))>262144)throw new Error("Invalid history input");
  const id=randomUUID(),entry:HistoryEntry={id,model,createdAt:new Date().toISOString(),messages:[...messages],output:"",status:"running"};
  await this.change(rows=>[entry,...rows].slice(0,100));return id;
 }
 checkpoint(id:string,output:string,message?:string){
  return this.change(rows=>{
   const row=rows.find(r=>r.id===id&&r.status==="running");
   if(!row)throw new Error("Unknown or terminal history entry");
   const messages=message===undefined?row.messages:[...row.messages,message];
   if(messages.length>20||Buffer.byteLength(JSON.stringify(messages))>262144)throw new Error("History input limit exceeded");
   return rows.map(r=>r.id===id?{...r,messages,output:output.slice(0,262144)}:r);
  });
 }
 finish(id:string,status:Exclude<HistoryEntry["status"],"running">,output:string,sessionId?:string){
  return this.change(rows=>{
   if(!rows.some(r=>r.id===id&&r.status==="running"))throw new Error("Unknown or terminal history entry");
   return rows.map(r=>r.id===id?{...r,status,output:output.slice(0,262144),sessionId}:r);
  });
 }
 recover(){return this.change(rows=>rows.map(r=>r.status==="running"?{...r,status:"unknown"}:r));}
}
