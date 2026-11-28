import {realpath,readdir,lstat,open} from "node:fs/promises";
import path from "node:path";

export type SearchHit={file:string;line?:number;text?:string};
export type SearchResult={hits:SearchHit[];truncated:boolean;skipped:number};
const ignored=new Set([".git","node_modules",".venv","__pycache__",".ssh",".aws",".gnupg"]);
const sensitive=(name:string)=>/^\.env(?:\.|$)|\.(?:pem|key|pfx|p12)$/i.test(name);
export async function searchProject(projectRoot:string,query:string,mode:"file"|"text",signal?:AbortSignal):Promise<SearchResult>{
  if(!path.isAbsolute(projectRoot)||!query.trim()||query.length>512||!["file","text"].includes(mode))throw new Error("Invalid search request");
  const root=await realpath(projectRoot);
  const needle=query.toLowerCase();
  const hits:SearchHit[]=[];
  let visited=0,skipped=0,truncated=false,bytes=0;
  const deadline=Date.now()+5000;
  const within=(candidate:string)=>{const relative=path.relative(root,candidate);return relative!==""&&!path.isAbsolute(relative)&&relative!==".."&&!relative.startsWith(".."+path.sep);};
  async function walk(dir:string,depth:number):Promise<void>{
    signal?.throwIfAborted();
    if(depth>32){truncated=true;return;}
    for(const entry of await readdir(dir,{withFileTypes:true})){
      signal?.throwIfAborted();
      if(++visited>10000||hits.length>=200||Date.now()>deadline||bytes>=16*1024*1024){truncated=true;return;}
      if(ignored.has(entry.name.toLowerCase())||sensitive(entry.name)||entry.isSymbolicLink()){skipped++;continue;}
      const file=path.join(dir,entry.name);
      try{
        const resolved=await realpath(file);
        if(!within(resolved)||resolved!==file){skipped++;continue;}
        const info=await lstat(file);
        if(info.isDirectory()){await walk(file,depth+1);if(truncated)return;continue;}
        if(!info.isFile()){skipped++;continue;}
        const relative=path.relative(root,file).split(path.sep).join("/");
        if(mode==="file"){if(relative.toLowerCase().includes(needle))hits.push({file:relative});continue;}
        if(info.size>256*1024){skipped++;continue;}
        const handle=await open(file,"r");
        let content:Buffer;
        try{
          const buffer=Buffer.alloc(256*1024+1);
          const result=await handle.read(buffer,0,buffer.length,0);
          content=buffer.subarray(0,result.bytesRead);
        }finally{await handle.close();}
        bytes+=content.length;
        if(content.length>256*1024||content.includes(0)){skipped++;continue;}
        const lines=content.toString("utf8").split(/\r?\n/);
        for(let i=0;i<lines.length;i++){
          const index=lines[i].toLowerCase().indexOf(needle);
          if(index>=0)hits.push({file:relative,line:i+1,text:lines[i].slice(Math.max(0,index-80),index+240)});
          if(hits.length>=200){truncated=true;return;}
        }
      }catch(error){if(signal?.aborted)throw error;skipped++;}
    }
  }
  await walk(root,0);
  return {hits,truncated,skipped};
}
