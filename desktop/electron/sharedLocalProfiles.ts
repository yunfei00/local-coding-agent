export type SharedLocalProfile={id:string;label:string;model:string;port:number;context:number;maxOutput:number};
export function sharedLocalProfiles(value:unknown):SharedLocalProfile[]{
 const catalog=value as {connections?:unknown;profiles?:unknown};
 if(!Array.isArray(catalog?.connections)||!Array.isArray(catalog?.profiles))return [];
 const connections=catalog.connections;
 const result:SharedLocalProfile[]=[];
 for(const p of catalog.profiles){
  if(!p||typeof p.model_profile_id!=="string"||typeof p.model_id!=="string"||!/^[a-zA-Z0-9][a-zA-Z0-9_.:/-]{0,127}$/.test(p.model_id))continue;
  const c=connections.find(c=>c?.connection_id===p.connection_id);
  if(!c||c.enabled!==true||c.provider_type!=="ollama"||typeof c.base_url!=="string")continue;
  let url:URL;try{url=new URL(c.base_url);}catch{continue;}
  if(url.protocol!=="http:"||!["127.0.0.1","localhost"].includes(url.hostname)||url.username||url.password||url.search||url.hash||url.pathname!=="/")continue;
  const context=p.context_window??8192,maxOutput=p.max_output_tokens??512;
  if(!Number.isSafeInteger(context)||context<1024||context>262144||!Number.isSafeInteger(maxOutput)||maxOutput<1||maxOutput>=context)continue;
  result.push({id:p.model_profile_id,label:String(p.display_name??p.model_id).slice(0,128),model:p.model_id,port:Number(url.port||80),context,maxOutput});
 }
 return result.slice(0,500);
}
