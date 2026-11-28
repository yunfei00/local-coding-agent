import {createServer} from "node:http";
import {randomBytes,timingSafeEqual} from "node:crypto";
import {Readable,Transform} from "node:stream";
import {pipeline} from "node:stream/promises";

export type GatewayLimits={requests:number;inputBytes:number;maxOutput:number;durationMs:number;allowTools?:boolean;upstreamBaseUrl?:string;requestMs?:number;reserveTokens?:number;temperature?:number;reasoningEffort?:"none";reserve?: (inputBytes:number, maxOutput:number)=>Promise<void>};
export type CompatibleEndpoint = { baseUrl:string; apiKey?:string };
export async function startLocalModelGateway(model:string,upstreamPort:number,limits:GatewayLimits){
  if(!/^[a-zA-Z0-9][a-zA-Z0-9_.:/-]{0,127}$/.test(model))throw new Error("Invalid model");
  if(!Number.isInteger(upstreamPort)||upstreamPort<1||upstreamPort>65535)throw new Error("Invalid upstream port");
  for(const n of [limits.requests,limits.inputBytes,limits.maxOutput,limits.durationMs])if(!Number.isSafeInteger(n)||n<1)throw new Error("Invalid gateway limit");
  const upstreamUrl=new URL(limits.upstreamBaseUrl??('http://127.0.0.1:'+upstreamPort));
  if(upstreamUrl.protocol!=="http:"||upstreamUrl.username||upstreamUrl.password||upstreamUrl.search||upstreamUrl.hash||upstreamUrl.pathname!=="/"||! /^(localhost|127\.\d+\.\d+\.\d+|10\.\d+\.\d+\.\d+|192\.168\.\d+\.\d+|172\.(1[6-9]|2\d|3[01])\.\d+\.\d+)$/.test(upstreamUrl.hostname))throw new Error("Invalid private Ollama address");
  return startCompatibleGateway(model,{baseUrl:upstreamUrl.origin+"/v1"},limits);
}

export async function startCompatibleGateway(model:string,endpoint:CompatibleEndpoint,limits:GatewayLimits){
  if (!model || model.length > 256 || /[\r\n\0]/.test(model)) throw new Error("Invalid model");
  const upstreamUrl = new URL(endpoint.baseUrl);
  if (!["http:", "https:"].includes(upstreamUrl.protocol) || upstreamUrl.username || upstreamUrl.password || upstreamUrl.search || upstreamUrl.hash) {
    throw new Error("Invalid configured provider address");
  }
  for(const n of [limits.requests,limits.inputBytes,limits.maxOutput,limits.durationMs])if(!Number.isSafeInteger(n)||n<1)throw new Error("Invalid gateway limit");
  const upstream = upstreamUrl.href.replace(/\/+$/,"") + "/chat/completions";
  const token=randomBytes(32).toString("hex");
  const deadline=Date.now()+limits.durationMs;
  let requests=0,bytes=0,reserved=0,closed=false;
  let upstreamRequests=0;
  let upstreamQuotaStatus: number | undefined;
  let lastStatus:number|undefined;
  let failure:string|undefined;
  const active=new Set<AbortController>();
  const server=createServer(async(req,res)=>{
    const reject=(status:number,reason?:string)=>{
      lastStatus=status;failure=reason;
      if(!res.headersSent)res.writeHead(status,{"content-type":"application/json"});
      res.end(JSON.stringify({error:{message:reason ?? "Request rejected"}}));
    };
    const actual=Buffer.from(req.headers.authorization??"");
    const expected=Buffer.from("Bearer "+token);
    if(actual.length!==expected.length||!timingSafeEqual(actual,expected))return reject(401);
    if(req.method!=="POST"||req.url!=="/v1/chat/completions")return reject(404);
    // Return a non-retryable status to the runtime after quota or rate denial.
    // Subsequent requests never reserve budget or reach the provider.
    if(upstreamQuotaStatus)return reject(402,`Provider quota/rate limit reached (HTTP ${upstreamQuotaStatus})`);
    if(closed||Date.now()>=deadline||requests>=limits.requests||active.size)return reject(429);
    requests++;
    const controller=new AbortController();active.add(controller);
    const timer=setTimeout(()=>controller.abort(),Math.max(1,Math.min(limits.requestMs ?? Infinity,deadline-Date.now())));
    const abortBody=()=>{if(!req.complete)req.destroy();};
    controller.signal.addEventListener("abort",abortBody,{once:true});
    res.once("close",()=>controller.abort());
    try{
      const chunks:Buffer[]=[];
      for await(const chunk of req){
        const b=Buffer.from(chunk);bytes+=b.length;
        if(bytes>limits.inputBytes){reject(413);return;}
        chunks.push(b);
      }
      const body=JSON.parse(Buffer.concat(chunks).toString("utf8"));
      if(!body||body.model!==model||!Array.isArray(body.messages))return reject(400,"Model or messages do not match the selected profile");
      if(!limits.allowTools && ((body.tools!==undefined && (!Array.isArray(body.tools)||body.tools.length!==0)) || (body.tool_choice!==undefined && body.tool_choice!=="none" && body.tool_choice!=="auto")))return reject(403);
      if(limits.allowTools && body.tools!==undefined && (!Array.isArray(body.tools)||body.tools.length>64))return reject(400,"Tool schema exceeds relay limits");
      for(const key of ["max_tokens","max_completion_tokens"]){
        if(body[key]!==undefined&&(!Number.isSafeInteger(body[key])||body[key]<1))return reject(400,"Invalid output token limit");
      }
      const max=Math.min(limits.maxOutput,body.max_tokens??limits.maxOutput,body.max_completion_tokens??limits.maxOutput);
      const requestBytes = Buffer.byteLength(JSON.stringify(body));
      const reservation = requestBytes + max;
      if (limits.reserveTokens !== undefined && reserved + reservation > limits.reserveTokens) return reject(429,"Model token budget exhausted");
      reserved += reservation;
      try {
        await limits.reserve?.(requestBytes,max);
      } catch {
        return reject(429,"Online reservation denied by the persisted budget");
      }
      controller.signal.throwIfAborted();
      upstreamRequests++;
      const response=await fetch(upstream,{
        method:"POST",headers:{"content-type":"application/json",...(endpoint.apiKey ? {authorization:"Bearer "+endpoint.apiKey} : {})},redirect:"error",signal:controller.signal,
        body:JSON.stringify({model,messages:body.messages,stream:body.stream===true,max_tokens:max,
          ...(limits.temperature === undefined ? {} : {temperature:limits.temperature}),
          ...(limits.reasoningEffort ? {reasoning_effort:limits.reasoningEffort} : {}),
          ...(body.stream_options && body.stream===true ? {stream_options:body.stream_options} : {}),
          ...(limits.allowTools?{tools:body.tools,tool_choice:body.tool_choice}:{})})
      });
      if (!response.ok) {
        if (response.status === 402 || response.status === 429) upstreamQuotaStatus = response.status;
        await response.body?.cancel();
        if (upstreamQuotaStatus) return reject(402,`Provider quota/rate limit reached (HTTP ${upstreamQuotaStatus})`);
        return reject(response.status,"Provider rejected model request");
      }
      lastStatus=response.status;
      failure=undefined;
      res.writeHead(response.status,{"content-type":response.headers.get("content-type")??"application/json"});
      if(response.body){
        let outputBytes=0;
        const bounded=new Transform({transform(chunk,_encoding,callback){
          outputBytes+=Buffer.byteLength(chunk);
          if(outputBytes>2*1024*1024){controller.abort();callback(new Error("Gateway output exceeds byte limit"));return;}
          callback(null,chunk);
        }});
        await pipeline(Readable.fromWeb(response.body as Parameters<typeof Readable.fromWeb>[0]),bounded,res,{signal:controller.signal});
      }
      else res.end();
    }catch{if(!res.headersSent)reject(502);else res.destroy();}
    finally{clearTimeout(timer);controller.signal.removeEventListener("abort",abortBody);active.delete(controller);}
  });
  server.requestTimeout=Math.min(limits.durationMs,30000);
  await new Promise<void>((resolve,reject)=>{server.once("error",reject);server.listen(0,"127.0.0.1",()=>{server.removeListener("error",reject);resolve();});});
  const address=server.address();
  if(!address||typeof address==="string")throw new Error("Gateway address unavailable");
  return {port:address.port,token,usage:()=>({requests,upstreamRequests,bytes,reserved,lastStatus,failure}),close:async()=>{
    closed=true;for(const c of active)c.abort();
    await new Promise<void>((resolve,reject)=>{server.close(e=>e?reject(e):resolve());server.closeAllConnections();});
  }};
}
