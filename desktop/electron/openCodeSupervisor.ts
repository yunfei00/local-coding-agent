import { spawn, ChildProcess } from "node:child_process";
import { randomBytes, createHash } from "node:crypto";
import { readFile, mkdir } from "node:fs/promises";
import path from "node:path";

const HASH = "98cb0aa854c7c015cf6febafa7afb872c359bfe5a823a526f3b4fd347a9e9677";
export class OpenCodeSupervisor {
  private child?: ChildProcess;
  private origin?: string;
  private password?: string;
  private starting = false;
  private stopping = false;
  async start(binary: string, isolatedRoot: string): Promise<void> {
    if (this.child || this.starting || this.stopping) throw new Error("Sidecar already owned");
    this.starting = true;
    try {
      if (process.platform !== "win32") throw new Error("Windows sidecar required");
      if (!path.isAbsolute(binary) || !path.isAbsolute(isolatedRoot)) throw new Error("Absolute paths required");
      if (createHash("sha256").update(await readFile(binary)).digest("hex") !== HASH) throw new Error("Sidecar checksum mismatch");
      await mkdir(isolatedRoot, {recursive:true});
      const password = randomBytes(32).toString("hex");
      this.password = password;
      const env: NodeJS.ProcessEnv = {};
      for (const key of ["SystemRoot","WINDIR","PATH","TEMP","TMP","COMSPEC","PATHEXT"]) if (process.env[key]) env[key] = process.env[key];
      Object.assign(env, {OPENCODE_TEST_HOME:isolatedRoot, OPENCODE_CONFIG_DIR:path.join(isolatedRoot,"config"),
        XDG_CONFIG_HOME:path.join(isolatedRoot,"config"), XDG_DATA_HOME:path.join(isolatedRoot,"data"),
        XDG_CACHE_HOME:path.join(isolatedRoot,"cache"), XDG_STATE_HOME:path.join(isolatedRoot,"state"),
        OPENCODE_PASSWORD:password, OPENCODE_DISABLE_MODELS_FETCH:"1", OPENCODE_DISABLE_PROJECT_CONFIG:"1",
        OPENCODE_DISABLE_CLAUDE_CODE:"1", OPENCODE_CONFIG_CONTENT:JSON.stringify({providers:{},policies:[{action:"provider.use",resource:"*",effect:"deny"}]})});
      const child = spawn(binary,["serve","--hostname","127.0.0.1","--port","0"],{cwd:isolatedRoot,env,windowsHide:true,stdio:["ignore","pipe","pipe"]});
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
      if(!["2.2.6","v2.2.6","opencode v2.2.6"].includes(info.version ?? "")) throw new Error("Sidecar version mismatch");
    } catch(error) { await this.stop(); throw error; }
    finally { this.starting=false; }
  }
  private headers(): Record<string,string> {
    if(!this.origin || !this.password || this.stopping) throw new Error("Sidecar unavailable");
    return {authorization:"Basic "+Buffer.from("opencode:"+this.password).toString("base64")};
  }
  async request(route:string,method="GET",body?:unknown):Promise<unknown>{
    if(!/^\/api\/(info|session(?:\/[A-Za-z0-9_%.-]+(?:\/interrupt)?)?)$/.test(route)) throw new Error("Route not allowed");
    const response=await fetch(this.origin+route,{method,headers:{...this.headers(),"content-type":"application/json"},body:body===undefined?undefined:JSON.stringify(body),redirect:"error",signal:AbortSignal.timeout(8000)});
    if(!response.ok){await response.body?.cancel();throw new Error("Sidecar HTTP "+response.status);}
    return response.status===204?undefined:response.json();
  }
  async events(signal:AbortSignal):Promise<Response>{
    const response=await fetch(this.origin+"/api/event",{headers:this.headers(),redirect:"error",signal});
    if(!response.ok){await response.body?.cancel();throw new Error("Event HTTP "+response.status);}
    return response;
  }
  async stop():Promise<void>{
    this.origin=undefined;this.password=undefined;
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
