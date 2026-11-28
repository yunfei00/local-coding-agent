import { createServer } from "node:http";
import { randomBytes } from "node:crypto";
import { EngineEventBridge } from "./engineEventBridge";
import { buildLocalModelConfig } from "./openCodeModelConfig";
import { recoverCompletedExchange } from "./openCodeRecovery";
import { OpenCodeSupervisor } from "./openCodeSupervisor";
import type {RuntimeProbe} from "./openCodeUpdateManager";

export const probeOpenCodeCompatibility: RuntimeProbe = async (candidate, directory) => {
  const marker = "lca-runtime-probe";
  const token = randomBytes(32).toString("hex");
  let requests = 0;
  const provider = createServer(async (request,response) => {
    if (request.method !== "POST" || request.url !== "/v1/chat/completions" || request.headers.authorization !== "Bearer "+token) {
      response.writeHead(401).end();
      return;
    }
    const input:Buffer[] = [];
    let length = 0;
    for await (const chunk of request) {
      length += chunk.length;
      if (length > 65536) { response.writeHead(413).end(); return; }
      input.push(chunk);
    }
    try {
      const body=JSON.parse(Buffer.concat(input).toString("utf8"));
      if (body.model !== marker || body.stream !== true) { response.writeHead(400).end(); return; }
    } catch { response.writeHead(400).end(); return; }
    requests++;
    response.writeHead(200,{"content-type":"text/event-stream"});
    response.end("data: "+JSON.stringify({id:"oc-probe",object:"chat.completion.chunk",model:marker,
      choices:[{index:0,delta:{role:"assistant",content:marker},finish_reason:"stop"}]})+"\n\ndata: [DONE]\n\n");
  });
  const supervisor = new OpenCodeSupervisor();
  const signal = new AbortController();
  const timer = setTimeout(()=>signal.abort(),30_000);
  let follow:Promise<void>|undefined;
  try {
    await new Promise<void>((resolve,reject)=>{provider.once("error",reject);provider.listen(0,"127.0.0.1",resolve);});
    const address = provider.address();
    if (!address || typeof address === "string") throw new Error("兼容性模型服务未启动");
    await supervisor.start(candidate.binary,directory,{
      allowPrompt:true,compatibilityProbe:true,binarySha256:candidate.sha256,
      expectedVersion:[candidate.version,candidate.version.slice(1),"opencode "+candidate.version],
      configContent:JSON.stringify(buildLocalModelConfig({model:marker,context:8192,maxOutput:128},{port:address.port,token})),
    });
    const result = await supervisor.request("/api/session","POST", {title:marker,
      permissions:[{action:"*",resource:"*",effect:"deny"},{action:"edit",resource:"compatibility.txt",effect:"ask"}]}) as {data?:{id?:string}};
    const session = result.data?.id;
    if (!session) throw new Error("运行时会话协议不兼容");
    const route = "/api/session/"+encodeURIComponent(session);
    let ready!:()=>void, ask!:()=>void;
    let text = "";
    let outcome = "";
    let permissionID:unknown;
    const subscribed = new Promise<void>(resolve=>{ready=resolve;});
    const asked = new Promise<void>(resolve=>{ask=resolve;});
    follow = new EngineEventBridge(supervisor,0).follow(session,signal.signal,event=>{
      if (event.kind==="snapshot") ready();
      if (event.kind==="approval") { permissionID=(event.payload as {requestId?:unknown}).requestId; ask(); }
      if (event.kind==="text") text+=(event.payload as {delta:string}).delta;
      if (event.kind==="execution-ended") {
        outcome=(event.payload as {outcome:string}).outcome;
        signal.abort();
      }
    });
    void follow.catch(()=>{});
    await Promise.race([subscribed,follow]);
    signal.signal.throwIfAborted();
    const permission = await supervisor.request(route+"/permission","POST") as {data?:{id?:string;effect?:string}};
    await Promise.race([asked,follow]);
    if (permission.data?.effect !== "ask" || !permission.data.id || permissionID !== permission.data.id) {
      throw new Error("运行时权限事件协议不兼容");
    }
    await supervisor.request(route+"/permission/"+encodeURIComponent(permission.data.id)+"/reply","POST",{decision:"reject"});
    const messageId="msg_probe_"+randomBytes(12).toString("hex");
    await supervisor.request(route+"/prompt","POST",{id:messageId,text:"Compatibility probe"});
    await follow;
    if (outcome !== "succeeded" || text !== marker || requests !== 1) throw new Error("运行时 SSE 或 Provider 配置不兼容");
    const recovered = recoverCompletedExchange(await supervisor.request(route+"/context"),messageId);
    if (recovered?.outcome !== "succeeded" || recovered.text !== marker) throw new Error("运行时持久会话记录不兼容");
    await supervisor.request(route,"DELETE");
  } finally {
    clearTimeout(timer);
    signal.abort();
    await follow?.catch(()=>{});
    try {await supervisor.stop();}
    finally {await new Promise<void>(resolve=>{provider.close(()=>resolve());provider.closeAllConnections();});}
  }
};
