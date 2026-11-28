import {buildLocalModelConfig, type LocalModelProfile} from "./openCodeModelConfig";
import { spawn, ChildProcess } from "node:child_process";
import { randomBytes, createHash } from "node:crypto";
import { readFile, mkdir } from "node:fs/promises";
import path from "node:path";

const DEFAULT_HASH = "98cb0aa854c7c015cf6febafa7afb872c359bfe5a823a526f3b4fd347a9e9677";
export type OpenCodeSupervisorOptions = {
  configContent?: string;
  allowPrompt?: boolean;
  expectedVersion?: string[];
  binarySha256?: string;
  cwd?: string;
  compatibilityProbe?: boolean;
};
export class OpenCodeSupervisor {
  private child?: ChildProcess;
  private origin?: string;
  private password?: string;
  private localChat = false;
  private fixtureTools = false;
  private starting = false;
  private stopping = false;
  private options: OpenCodeSupervisorOptions = {};
  async start(binary: string, isolatedRoot: string, localOrOptions?: {profile:LocalModelProfile;gateway:{port:number;token:string};fixtureTools?:boolean} | OpenCodeSupervisorOptions): Promise<void> {
    if (this.child || this.starting || this.stopping) throw new Error("Sidecar already owned");
    this.starting = true;
    const local = localOrOptions && "profile" in localOrOptions ? localOrOptions as {profile:LocalModelProfile;gateway:{port:number;token:string};fixtureTools?:boolean} : undefined;
    const options = localOrOptions && !("profile" in localOrOptions) ? localOrOptions as OpenCodeSupervisorOptions : {};
    this.options = options;
    try {
      if (process.platform !== "win32") throw new Error("Windows sidecar required");
      if (!path.isAbsolute(binary) || !path.isAbsolute(isolatedRoot)) throw new Error("Absolute paths required");
      const expectedHash = options.binarySha256 ?? DEFAULT_HASH;
      if (createHash("sha256").update(await readFile(binary)).digest("hex") !== expectedHash) throw new Error("Sidecar checksum mismatch");
      await mkdir(isolatedRoot, {recursive:true});
      const config = local ? buildLocalModelConfig(local.profile,local.gateway,local.fixtureTools===true) : (options.configContent ? JSON.parse(options.configContent) : {providers:{},policies:[{action:"provider.use",resource:"*",effect:"deny"}]});
      this.localChat = !!local || options.allowPrompt === true;
      this.fixtureTools = local?.fixtureTools===true;
      const password = randomBytes(32).toString("hex");
      this.password = password;
      const env: NodeJS.ProcessEnv = {};
      for (const key of ["SystemRoot","WINDIR","PATH","TEMP","TMP","COMSPEC","PATHEXT","USERPROFILE","LOCALAPPDATA","APPDATA","ProgramFiles","ProgramFiles(x86)"]) if (process.env[key]) env[key] = process.env[key];
      const configContent = JSON.stringify(config);
      Object.assign(env, {OPENCODE_TEST_HOME:isolatedRoot, OPENCODE_CONFIG_DIR:path.join(isolatedRoot,"config"),
        XDG_CONFIG_HOME:path.join(isolatedRoot,"config"), XDG_DATA_HOME:path.join(isolatedRoot,"data"),
        XDG_CACHE_HOME:path.join(isolatedRoot,"cache"), XDG_STATE_HOME:path.join(isolatedRoot,"state"),
        OPENCODE_PASSWORD:password, OPENCODE_DISABLE_MODELS_FETCH:"1", OPENCODE_DISABLE_PROJECT_CONFIG:"1",
        OPENCODE_DISABLE_CLAUDE_CODE:"1", OPENCODE_CONFIG_CONTENT:configContent});
      const serveCwd = options.cwd ?? isolatedRoot;
      const child = spawn(binary,["serve","--hostname","127.0.0.1","--port","0"],{cwd:serveCwd,env,windowsHide:true,stdio:["ignore","pipe","pipe"]});
      this.child = child;
      child.stderr?.resume();
      child.on("error",()=>{this.origin=undefined;});
      child.once("close",()=>{if(this.child===child){this.child=undefined;this.origin=undefined;this.password=undefined;}});
      const origin = await new Promise<string>((resolve,reject)=>{
        let buffer="";
        const timer=setTimeout(()=>finish(new Error("Sidecar readiness timeout")),30000);
        const onError=()=>finish(new Error("Sidecar startup failed"));
        const onExit=()=>finish(new Error("Sidecar exited before readiness"));
        const onData=(chunk:Buffer)=>{
          buffer=(buffer+chunk.toString()).slice(-4096);
          const match=buffer.match(/http:\/\/127\.0\.0\.1:(\d+)/);
          if(match && Number(match[1])>0 && Number(match[1])<=65535) finish(undefined,match[0]);
        };
        function finish(error?:Error,url?:string){
          clearTimeout(timer);child.removeListener("error",onError);child.removeListener("close",onExit);child.stdout?.removeListener("data",onData);
          child.stdout?.resume();
          if(error) reject(error); else resolve(url!);
        }
        child.once("error",onError);child.once("close",onExit);child.stdout?.on("data",onData);
      });
      if(this.child!==child) throw new Error("Sidecar exited");
      this.origin=origin;
      const unauth=await fetch(origin+"/api/info",{redirect:"error",signal:AbortSignal.timeout(8000)});
      await unauth.body?.cancel();
      if(unauth.status!==401) throw new Error("Sidecar authentication missing");
      const info=await this.request("/api/info") as {version?:string};
      const allowedVersions = options.expectedVersion ?? ["2.2.6","v2.2.6","opencode v2.2.6"];
      if(!allowedVersions.includes(info.version ?? "")) throw new Error("Sidecar version mismatch");
    } catch(error) { await this.stop(); throw error; }
    finally { this.starting=false; }
  }
  private headers(): Record<string,string> {
    if(!this.origin || !this.password || this.stopping) throw new Error("Sidecar unavailable");
    return {authorization:"Basic "+Buffer.from("opencode:"+this.password).toString("base64")};
  }
  async request(route:string,method="GET",body?:unknown):Promise<unknown>{
    const session = /^\/api\/session\/([A-Za-z0-9_-]+)(\/interrupt|\/prompt|\/model)?$/.exec(route);
    const approval = /^\/api\/session\/[A-Za-z0-9_-]+\/permission\/per[A-Za-z0-9_-]+\/reply$/.test(route);
    const probePermission = this.options.compatibilityProbe === true && /^\/api\/session\/[A-Za-z0-9_-]+\/permission$/.test(route);
    const promptAllowed = this.localChat || this.options.allowPrompt === true;
    const allowed = (method==="GET" && (route==="/api/info" || route==="/api/session" || route==="/api/session/active" || (session && !session[2] && session[1]))) ||
      (method==="POST" && (route==="/api/session" || (session && (session[2]==="/interrupt" || (promptAllowed && session[2]==="/prompt"))))) ||
      (this.options.allowPrompt === true && (
        ((method==="DELETE" || method==="PATCH") && !!session && !session[2]) ||
        (method==="POST" && (approval || probePermission || session?.[2]==="/model"))));
    if(!allowed) throw new Error("Route not allowed");
    if(method==="POST" && route==="/api/session"){
      const input=body as {title?:unknown;permissions?:unknown;location?:{directory?:unknown}}|undefined;
      if(typeof input?.title!=="string" || !Array.isArray(input.permissions)) throw new Error("Invalid session create request");
      if(this.options.allowPrompt !== true){
        if(JSON.stringify(input.permissions)!==JSON.stringify([{action:"*",resource:"*",effect:"deny"}])) throw new Error("Only deny-all diagnostic sessions allowed");
        body={title:input.title,permissions:[{action:"*",resource:"*",effect:"deny"},...(this.fixtureTools?[{action:"read",resource:"seed.txt",effect:"allow"},{action:"read",resource:"add.cjs",effect:"allow"},{action:"edit",resource:"add.cjs",effect:"allow"},{action:"edit",resource:"result.txt",effect:"allow"},{action:"shell",resource:"echo P2_SHELL_CHECK",effect:"allow"},{action:"shell",resource:"git status --short",effect:"allow"},{action:"shell",resource:"git diff -- add.cjs",effect:"allow"}]:[])]};
      } else {
        if (input.location && (typeof input.location.directory !== "string" || !path.isAbsolute(input.location.directory)
          || !this.options.cwd || path.relative(this.options.cwd,input.location.directory) !== "")) {
          throw new Error("Invalid project location");
        }
        body={title:input.title,permissions:input.permissions,...(input.location ? {location:input.location} : {})};
      }
    } else if (method==="POST" && probePermission) {
      body={action:"edit",resources:["compatibility.txt"]};
    } else if (method==="PATCH") {
      const input=body as {permissions?:unknown}|undefined;
      if (!Array.isArray(input?.permissions)) throw new Error("Invalid session permissions");
      body={permissions:input.permissions};
    } else if (method==="POST" && session?.[2]==="/model") {
      const model=(body as {model?:{id?:unknown;providerID?:unknown}}|undefined)?.model;
      if (typeof model?.id !== "string" || typeof model.providerID !== "string") throw new Error("Invalid session model");
      body={model:{id:model.id,providerID:model.providerID}};
    } else if (method==="POST" && approval) {
      const input=body as {decision?:unknown}|undefined;
      if (input?.decision !== "once" && input?.decision !== "reject") throw new Error("Invalid permission decision");
      body={decision:input.decision};
    } else if(method==="POST" && session?.[2]==="/prompt") {
      const input=body as {text?:unknown;delivery?:unknown;id?:unknown;resume?:unknown}|undefined;
      if(typeof input?.text!=="string" || !input.text.trim() || Buffer.byteLength(input.text)>65536) throw new Error("Invalid prompt request");
      if (input.delivery !== undefined && (this.options.allowPrompt !== true || input.delivery !== "steer"
        || typeof input.id !== "string" || !/^msg_[a-zA-Z0-9_-]{1,128}$/.test(input.id) || input.resume !== false)) {
        throw new Error("Invalid prompt delivery");
      }
      body={text:input.text,...(input.delivery ? {delivery:input.delivery,id:input.id,resume:false} : {})};
    } else if(body!==undefined) throw new Error("Unexpected request body");
    const response=await fetch(this.origin+route,{method,headers:{...this.headers(),"content-type":"application/json"},body:body===undefined?undefined:JSON.stringify(body),redirect:"error",signal:AbortSignal.timeout(promptAllowed ? 30000 : 8000)});
    if(!response.ok){await response.body?.cancel();throw new SidecarHttpError(response.status);}
    return response.status===204?undefined:response.json();
  }
  async events(signal:AbortSignal):Promise<Response>{
    const response=await fetch(this.origin+"/api/event",{headers:this.headers(),redirect:"error",signal});
    if(!response.ok){await response.body?.cancel();throw new Error("Event HTTP "+response.status);}
    return response;
  }
  isRunning():boolean{ return !!this.child && !!this.origin && !!this.password && !this.stopping; }
  async stop():Promise<void>{
    this.origin=undefined;this.password=undefined;this.localChat=false;this.fixtureTools=false;
    const child=this.child;
    if(!child || this.stopping)return;
    this.stopping=true;
    try {
      if(child.pid && child.exitCode===null && child.signalCode===null){
        const killer=spawn(path.join(process.env.SystemRoot || "C:\\Windows","System32","taskkill.exe"),["/PID",String(child.pid),"/T","/F"],{windowsHide:true,stdio:"ignore"});
        await new Promise<void>((resolve,reject)=>{const timer=setTimeout(()=>{killer.kill();reject(new Error("Sidecar cleanup timeout"));},8000);killer.once("error",e=>{clearTimeout(timer);reject(e);});killer.once("close",code=>{clearTimeout(timer);if(code===0 || child.exitCode!==null || child.signalCode!==null)resolve();else reject(new Error("Sidecar cleanup failed"));});});
      }
      if(this.child===child) await new Promise<void>((resolve,reject)=>{const timer=setTimeout(()=>{child.removeListener("close",done);reject(new Error("Sidecar close timeout"));},5000);function done(){clearTimeout(timer);resolve();}child.once("close",done);});
    } finally {this.stopping=false;}
  }
}

export class SidecarHttpError extends Error {
  constructor(readonly status: number) {
    super("Sidecar HTTP " + status);
  }
}
