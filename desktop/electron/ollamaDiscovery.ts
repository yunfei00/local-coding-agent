export async function discoverOllamaModels(port:number,fetcher:typeof fetch=fetch):Promise<string[]>{
 if(!Number.isInteger(port)||port<1||port>65535)throw new Error("Invalid Ollama port");
 const response=await fetcher("http://127.0.0.1:"+port+"/api/tags",{redirect:"error",signal:AbortSignal.timeout(5000)});
 if(!response.ok||!response.body)throw new Error("Ollama model discovery failed");
 const reader=response.body.getReader();
 const chunks:Uint8Array[]=[];let size=0;
 try{
  while(true){const {done,value}=await reader.read();if(done)break;size+=value.byteLength;if(size>1024*1024)throw new Error("Ollama response too large");chunks.push(value);}
 }finally{await reader.cancel().catch(()=>{});reader.releaseLock();}
 const body=JSON.parse(Buffer.concat(chunks).toString("utf8"));
 if(!Array.isArray(body?.models))throw new Error("Invalid Ollama model list");
 const names:string[]=body.models.map((m:{name?:unknown})=>m?.name).filter((name:unknown):name is string=>typeof name==="string"&&/^[a-zA-Z0-9][a-zA-Z0-9_.:/-]{0,127}$/.test(name));
 return [...new Set(names)].sort().slice(0,500);
}
