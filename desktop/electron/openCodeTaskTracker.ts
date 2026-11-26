import {randomUUID} from "node:crypto";
export type OpenCodeTaskSnapshot={id:string;engine:"opencode";model:string;status:"running"|"succeeded"|"failed"|"interrupted"|"unknown";startedAt:string;endedAt?:string;events:number;verified:false};
export class OpenCodeTaskTracker{
 private rows:OpenCodeTaskSnapshot[]=[];
 begin(model:string){
  if(this.rows.some(r=>r.status==="running"))throw new Error("OpenCode task already running");
  const row:OpenCodeTaskSnapshot={id:randomUUID(),engine:"opencode",model,startedAt:new Date().toISOString(),status:"running",events:0,verified:false};
  this.rows=[row,...this.rows].slice(0,100);return row.id;
 }
 progress(id:string){this.rows=this.rows.map(r=>r.id===id&&r.status==="running"?{...r,events:r.events+1}:r);}
 finish(id:string,status:Exclude<OpenCodeTaskSnapshot["status"],"running">){this.rows=this.rows.map(r=>r.id===id&&r.status==="running"?{...r,status,endedAt:new Date().toISOString()}:r);}
 list(){return this.rows.map(r=>({...r}));}
}
