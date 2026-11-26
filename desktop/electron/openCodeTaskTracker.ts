import {randomUUID} from "node:crypto";
import {existsSync,readFileSync,mkdirSync,writeFileSync,renameSync,unlinkSync} from "node:fs";
import path from "node:path";
export type OpenCodeTaskSnapshot={id:string;engine:"opencode";model:string;status:"running"|"waiting"|"stopping"|"succeeded"|"failed"|"interrupted"|"unknown";startedAt:string;endedAt?:string;events:number;verified:false};
type Status=OpenCodeTaskSnapshot["status"];
const active=(s:Status)=>["running","waiting","stopping"].includes(s);
export class OpenCodeTaskTracker{
 private rows:OpenCodeTaskSnapshot[]=[];
 constructor(private readonly file?:string){
  if(file&&existsSync(file)){
   const rows:unknown=JSON.parse(readFileSync(file,"utf8"));
   if(!Array.isArray(rows)||rows.length>100||rows.some(r=>!r||typeof r.id!=="string"||r.engine!=="opencode"||typeof r.model!=="string"||typeof r.startedAt!=="string"||!Number.isSafeInteger(r.events)||r.verified!==false||!["running","waiting","stopping","succeeded","failed","interrupted","unknown"].includes(r.status)))throw new Error("Invalid task journal");
   this.rows=rows.map(r=>active(r.status)?{...r,status:"unknown",endedAt:new Date().toISOString()}:r);
   this.save(this.rows);
  }
 }
 private save(rows:OpenCodeTaskSnapshot[]){
  if(this.file){
   mkdirSync(path.dirname(this.file),{recursive:true});
   const tmp=this.file+"."+randomUUID()+".tmp";
   try{writeFileSync(tmp,JSON.stringify(rows),{flag:"wx",mode:0o600});renameSync(tmp,this.file);}
   finally{try{unlinkSync(tmp);}catch{}}
  }
  this.rows=rows;
 }
 begin(model:string){
  if(this.rows.some(r=>active(r.status)))throw new Error("OpenCode task already running");
  const row:OpenCodeTaskSnapshot={id:randomUUID(),engine:"opencode",model,startedAt:new Date().toISOString(),status:"running",events:0,verified:false};
  this.save([row,...this.rows].slice(0,100));return row.id;
 }
 progress(id:string){this.save(this.rows.map(r=>r.id===id&&active(r.status)?{...r,events:r.events+1}:r));}
 transition(id:string,status:"running"|"waiting"|"stopping"){
  this.save(this.rows.map(r=>r.id===id&&active(r.status)&&r.status!=="stopping"?{...r,status}:r));
 }
 finish(id:string,status:Exclude<Status,"running"|"waiting"|"stopping">){this.save(this.rows.map(r=>r.id===id&&active(r.status)?{...r,status,endedAt:new Date().toISOString()}:r));}
 list(){return this.rows.map(r=>({...r}));}
}
