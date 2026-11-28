import {diagnoseHistorySession} from "./recoveryDiagnostic";
import {InteractiveTurnQueue} from "./interactiveTurnQueue";
import {OpenCodeTaskTracker} from "./openCodeTaskTracker";
import {sharedLocalProfiles} from "./sharedLocalProfiles";
import {discoverOllamaModels} from "./ollamaDiscovery";
import {OpenCodeHistory} from "./openCodeHistory";
import {readProjectDiff} from "./projectDiff";
import {searchProject} from "./projectSearch";
import { runLocalChat } from "./openCodeLocalChat";
import { acquireEngineLease } from "./engineLease";
import { EngineEventBridge } from "./engineEventBridge";
import { OpenCodeAdapter } from "./engineAdapter";
import { mkdtemp } from "node:fs/promises";
import { SidecarHttpError } from "./openCodeSupervisor";
import { OpenCodeRuntime } from "./openCodeRuntime";
import { selectOpenCodeProfile, startOpenCodeModel } from "./openCodeConfig";
import {OpenCodeUpdateManager} from "./openCodeUpdateManager";
import {probeOpenCodeCompatibility} from "./openCodeCompatibility";
import { isScopedResource, type OpenCodePermissionMode } from "./openCodePermissions";
import { recoverCompletedExchange } from "./openCodeRecovery";
import {
  app,
  BrowserWindow,
  clipboard,
  dialog,
  ipcMain,
  safeStorage,
  screen,
  shell
} from "electron";
import { ChildProcessWithoutNullStreams, spawn } from "node:child_process";
import { randomUUID } from "node:crypto";
import {
  appendFileSync,
  existsSync,
  mkdirSync,
  readFileSync,
  unlinkSync,
  writeFileSync
} from "node:fs";
import path from "node:path";
import WebSocket from "ws";

import { checkProtocolCompatibility } from "./protocol";
import {readProtectedJSON,writeProtectedCipher} from './vaultFile';
import {appendBoundedLog} from './runtimeLog';
import {UpdateManager} from './updateManager';
import {desktopArtifact} from "./desktopArtifact";

async function selectOpenCodeBinary(): Promise<{canceled:boolean;filePaths:string[]}> {
  const bundled=path.join(process.resourcesPath,"opencode","opencode.exe");
  if(app.isPackaged){
    if(!existsSync(bundled))throw new Error("Bundled OpenCode runtime missing; reinstall Local Coding Agent");
    return {canceled:false,filePaths:[bundled]};
  }
  const staged=path.resolve(app.getAppPath(),"../build/opencode-runtime/opencode.exe");
  if(existsSync(staged))return {canceled:false,filePaths:[staged]};
  return dialog.showOpenDialog({properties:["openFile"],filters:[{name:"OpenCode executable",extensions:["exe"]}]});
}

const APP_ID = "com.yunfei.localcodingagent";
// Expose the renderer's semantic controls to Windows UI Automation.
app.commandLine.appendSwitch("force-renderer-accessibility");
if (process.env.LCA_DESKTOP_DATA_DIR) {
  app.setPath("userData", path.resolve(process.env.LCA_DESKTOP_DATA_DIR));
}
app.setAppUserModelId(APP_ID);

type AgentStatus = {
  state: "starting" | "ready" | "error" | "stopped";
  host?: string;
  port?: number;
  version?: string;
  protocol?: string;
  error?: string;
};

type AgentEnvelope = {
  type: string;
  request_id?: string | null;
  thread_id?: string | null;
  turn_id?: string | null;
  timestamp?: string;
  payload?: Record<string, unknown>;
};

type PendingRequest = {
  expectedType: string;
  resolve: (value: AgentEnvelope) => void;
  reject: (error: Error) => void;
  timer: NodeJS.Timeout;
};

let mainWindow: BrowserWindow | null = null;
let agentProcess: ChildProcessWithoutNullStreams | null = null;
let agentSocket: WebSocket | null = null;
let agentToken: string | null = null;
let agentStatus: AgentStatus = { state: "starting" };
let stdoutBuffer = "";
let shuttingDown = false;
let quitInProgress = false;
let quitReady = false;
let rendererReady = false;
let packagedSmokeWritten = false;
let sessionOpenAIKey: string | null = null;
let sessionMcpSecrets: Record<string, Record<string, string>> = {};
let mcpReadFailed=false;
let lastAgentReady: {
  host: string;
  port: number;
  version: string;
  protocol: string;
} | null = null;
const pending = new Map<string, PendingRequest>();

async function maybeCompletePackagedSmoke():Promise<void> {
  const smokeFile=process.env.LCA_PACKAGED_SMOKE_FILE;
  if(!smokeFile||packagedSmokeWritten||!rendererReady||!lastAgentReady||agentStatus.state!=='ready')return;
  packagedSmokeWritten=true;
  try {
    const environment=(await sendRequest('maintenance.environment','maintenance.loaded')).payload;
    let projectCreated=false;
    const chatAcceptance=process.env.LCA_PACKAGED_CHAT_ACCEPTANCE==='1';
    if(process.env.LCA_NO_SDK_ACCEPTANCE==='1'||chatAcceptance){
      if(process.env.LCA_NO_SDK_ACCEPTANCE==='1'&&(!app.isPackaged||!environment?.bundled_backend||Object.values(environment.tools as Record<string,boolean>).some(Boolean)))throw new Error('No-SDK acceptance did not isolate development tools or bundled backend');
      const parent=path.join(process.env.LCA_DATA_DIR||app.getPath('userData'),'project-fixture');mkdirSync(parent,{recursive:true});
      const target=path.join(parent,'无 Git 工程 含空格');
      const project=existsSync(target)?await sendRequest('project.open','project.opened',{path:target}):await sendRequest('project.create','project.opened',{parent_path:parent,name:'无 Git 工程 含空格',initialize_git:true});
      projectCreated=!!project.payload?.project;
      if(!projectCreated)throw new Error('No Git project creation was not confirmed');
    }
    let chatVerified=false,fileVerified=false;
    let engine:string|undefined;
    if(chatAcceptance){
      if(!app.isPackaged||!process.env.LCA_DATA_DIR||!process.env.LCA_DESKTOP_DATA_DIR||process.env.LCA_PROVIDER!=='openai_compatible'||new URL(process.env.LCA_OPENAI_BASE_URL||'').hostname!=='127.0.0.1')throw new Error('Packaged chat acceptance requires isolated data and a loopback model');
      const nonce=String(process.env.LCA_PACKAGED_CHAT_NONCE||'');if(!/^PACKAGED_CHAT_[a-f0-9]{16}$/.test(nonce))throw new Error('Invalid owned chat canary');
      const target=path.join(process.env.LCA_DATA_DIR,'project-fixture','无 Git 工程 含空格','packaged-chat.txt');
      writeFileSync(target,nonce,{encoding:'utf8',flag:existsSync(target)?'r+':'wx'});
      await mainWindow!.webContents.executeJavaScript(`(async()=>{window.packagedSmokeEngine=null;window.localAgent.onAgentEvent(e=>{if(e.type==='turn.completed')window.packagedSmokeEngine=e.payload.engine;});const deadline=Date.now()+15000;while(document.querySelector('.send-button')?.disabled!==false&&Date.now()<deadline){const input=document.querySelector('.composer textarea');if(input&&!input.value){Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype,'value').set.call(input,'请用 read 工具完整读取 packaged-chat.txt，并报告原文。');input.dispatchEvent(new Event('input',{bubbles:true}));}await new Promise(r=>setTimeout(r,100));}const button=document.querySelector('.send-button');if(!button||button.disabled)throw Error('Composer unavailable');button.click();})()`);
      const deadline=Date.now()+45000;
      while(Date.now()<deadline){
        chatVerified=await mainWindow!.webContents.executeJavaScript(`!![...document.querySelectorAll('.message.agent')].find(e=>e.textContent.includes(${JSON.stringify(nonce)}))&&!document.querySelector('.stop-button')`);
        if(chatVerified)break;await new Promise(r=>setTimeout(r,150));
      }
      fileVerified=existsSync(target)&&readFileSync(target,'utf8')===nonce;
      engine=await mainWindow!.webContents.executeJavaScript('window.packagedSmokeEngine');
      if(!chatVerified||!fileVerified||engine!=='opencode')throw new Error(`Packaged composer/chat/file readback not verified (chat=${chatVerified}, file=${fileVerified}, completed=${engine==='opencode'})`);
    }
    writeFileSync(smokeFile,JSON.stringify({ok:true,renderer_ready:true,version:lastAgentReady.version,protocol:lastAgentReady.protocol,
      host:lastAgentReady.host,port:lastAgentReady.port,packaged:app.isPackaged,agent_executable:packagedAgentPath(),
      environment,no_sdk:process.env.LCA_NO_SDK_ACCEPTANCE==='1',no_git_project_created:projectCreated,chat_verified:chatVerified,file_verified:fileVerified,engine,engine_version:chatAcceptance?openCodeRuntime.status().version:undefined,model_decisions:chatAcceptance?'MOCK_LOOPBACK':'NOT_RUN'},null,2),'utf8');
    appendRuntimeLog('desktop.log','Packaged renderer/backend smoke completed');
  }catch(error){writeFileSync(smokeFile,JSON.stringify({ok:false,error:String(error)}),'utf8');}
  setTimeout(()=>app.quit(),250);
}

function repoRoot(): string {
  return path.resolve(__dirname, "..", "..");
}

function projectPythonPath(): string {
  return process.platform === "win32"
    ? path.join(repoRoot(), ".venv", "Scripts", "python.exe")
    : path.join(repoRoot(), ".venv", "bin", "python");
}

function packagedAgentPath(): string {
  return path.join(
    process.resourcesPath,
    "agent",
    process.platform === "win32" ? "lca-agent.exe" : "lca-agent"
  );
}

function logDirectory(): string {
  return path.join(app.getPath("userData"), "logs");
}

type SecretStorageMode =
  | "os_protected"
  | "session_only"
  | "environment"
  | "none";

function secretFilePath(): string {
  return path.join(app.getPath("userData"), "provider-secrets.json");
}

function mcpSecretFilePath(): string {
  return path.join(app.getPath("userData"), "mcp-secrets.json");
}

let modelCredentials: Record<string, string> | null = null;
function readModelCredentials(): Record<string, string> {
  if (modelCredentials !== null) return modelCredentials;
  const file = path.join(app.getPath("userData"), "model-secrets.json");
  if (!existsSync(file)) return modelCredentials = {};
  if (!safeStorage.isEncryptionAvailable()) throw new Error("Protected model credentials unavailable; restore OS storage before changing keys.");
  try {
    return modelCredentials = readProtectedJSON<Record<string,string>>(file,value=>safeStorage.decryptString(value),'flat');
  } catch {throw new Error("Cannot decrypt model credentials; existing encrypted file was preserved.");}
}
async function syncModelCredentials(): Promise<void> {
  await sendRequest("task.credentials.update", "task.loaded", {credentials: readModelCredentials()});
}
function storeModelCredentials(values: Record<string, string>): void {
  const file = path.join(app.getPath("userData"), "model-secrets.json");
  if (safeStorage.isEncryptionAvailable()) {
    writeProtectedCipher(file,safeStorage.encryptString(JSON.stringify(values)).toString("base64"));
  }
  modelCredentials = values;
}

function readMcpSecrets(): Record<string, Record<string, string>> {
  if (Object.keys(sessionMcpSecrets).length > 0) {
    return sessionMcpSecrets;
  }
  const file = mcpSecretFilePath();
  if (!existsSync(file) || !safeStorage.isEncryptionAvailable()) {
    return sessionMcpSecrets;
  }

  try {
    sessionMcpSecrets=readProtectedJSON<Record<string,Record<string,string>>>(file,value=>safeStorage.decryptString(value),'nested');
  } catch (error) {
    mcpReadFailed=true;
    appendRuntimeLog(
      "desktop.log",
      "MCP 加密凭据无法读取；原文件保留，不记录内容。"
    );
  }
  return sessionMcpSecrets;
}

function persistMcpSecrets(): void {
  if(mcpReadFailed)throw new Error("MCP 凭据库无法解密，未覆盖原文件；请从备份恢复。");
  const file = mcpSecretFilePath();
  if (!safeStorage.isEncryptionAvailable()) {
    return;
  }
  try {
    if (Object.keys(sessionMcpSecrets).length === 0) {
      if (existsSync(file)) {
        unlinkSync(file);
      }
      return;
    }
    const encrypted = safeStorage
      .encryptString(JSON.stringify(sessionMcpSecrets))
      .toString("base64");
    writeProtectedCipher(file,encrypted);
  } catch (error) {
    appendRuntimeLog(
      "desktop.log",
      "Unable to persist protected MCP secrets: " + String(error)
    );
  }
}

function updateMcpSecrets(
  serverId: string,
  action: "keep" | "set" | "clear",
  values?: Record<string, string>
): void {
  readMcpSecrets();
  if (action === "keep") {
    return;
  }
  if (action === "clear") {
    delete sessionMcpSecrets[serverId];
  } else {
    const next: Record<string, string> = {};
    for (const [key, value] of Object.entries(values ?? {})) {
      const name = String(key).trim();
      if (name && String(value)) {
        next[name] = String(value);
      }
    }
    if (Object.keys(next).length > 0) {
      sessionMcpSecrets[serverId] = next;
    } else {
      delete sessionMcpSecrets[serverId];
    }
  }
  persistMcpSecrets();
}

function mcpSecretStatuses(): Record<
  string,
  {
    configured: boolean;
    keys: string[];
    stored: boolean;
    mode: SecretStorageMode;
  }
> {
  const values = readMcpSecrets();
  const mode: SecretStorageMode = safeStorage.isEncryptionAvailable()
    ? "os_protected"
    : Object.keys(values).length > 0
      ? "session_only"
      : "none";
  return Object.fromEntries(
    Object.entries(values).map(([serverId, secrets]) => [
      serverId,
      {
        configured: Object.keys(secrets).length > 0,
        keys: Object.keys(secrets).sort(),
        stored: mode === "os_protected",
        mode
      }
    ])
  );
}

async function syncMcpSecretsToAgent(): Promise<void> {
  try {
    await sendRequest(
      "mcp.secrets",
      "mcp.changed",
      { secrets: readMcpSecrets() },
      {},
      45_000
    );
  } catch (error) {
    appendRuntimeLog(
      "desktop.log",
      "Unable to sync MCP secrets to Agent: " + String(error)
    );
  }
}


function readStoredOpenAIKey(): string | null {
  if (sessionOpenAIKey !== null) {
    return sessionOpenAIKey;
  }

  const file = secretFilePath();
  if (!existsSync(file) || !safeStorage.isEncryptionAvailable()) {
    return null;
  }

  try {
    const payload = JSON.parse(readFileSync(file, "utf8")) as {
      openai_api_key?: string;
    };
    if (!payload.openai_api_key) {
      return null;
    }
    const decrypted = safeStorage.decryptString(
      Buffer.from(payload.openai_api_key, "base64")
    );
    sessionOpenAIKey = decrypted;
    return decrypted;
  } catch (error) {
    appendRuntimeLog(
      "desktop.log",
      "旧版 Provider 加密凭据无法读取；原文件保留，不记录内容。"
    );
    return null;
  }
}

function currentOpenAIKey(): string | null {
  const stored = readStoredOpenAIKey();
  if (stored !== null) {
    return stored;
  }
  return process.env.LCA_OPENAI_API_KEY ?? null;
}

function secretStorageStatus(): {
  configured: boolean;
  stored: boolean;
  mode: SecretStorageMode;
} {
  const file = secretFilePath();
  const stored = existsSync(file) && safeStorage.isEncryptionAvailable();
  if (stored) {
    return {
      configured: Boolean(readStoredOpenAIKey()),
      stored: true,
      mode: "os_protected"
    };
  }
  if (sessionOpenAIKey) {
    return {
      configured: true,
      stored: false,
      mode: "session_only"
    };
  }
  if (process.env.LCA_OPENAI_API_KEY) {
    return {
      configured: true,
      stored: false,
      mode: "environment"
    };
  }
  return {
    configured: false,
    stored: false,
    mode: "none"
  };
}

function saveOpenAIKey(value: string): {
  configured: boolean;
  stored: boolean;
  mode: SecretStorageMode;
} {
  sessionOpenAIKey = value;
  const file = secretFilePath();

  if (!value) {
    if (existsSync(file)) {
      try {
        unlinkSync(file);
      } catch (error) {
        appendRuntimeLog(
          "desktop.log",
          "Unable to remove protected provider secret: " + String(error)
        );
      }
    }
    sessionOpenAIKey = "";
    return {
      configured: false,
      stored: false,
      mode: "none"
    };
  }

  if (!safeStorage.isEncryptionAvailable()) {
    return {
      configured: true,
      stored: false,
      mode: "session_only"
    };
  }

  try {
    const encrypted = safeStorage.encryptString(value).toString("base64");
    writeProtectedCipher(file,encrypted,'openai_api_key');
    return {
      configured: true,
      stored: true,
      mode: "os_protected"
    };
  } catch (error) {
    appendRuntimeLog(
      "desktop.log",
      "Unable to persist protected provider secret: " + String(error)
    );
    return {
      configured: true,
      stored: false,
      mode: "session_only"
    };
  }
}

async function syncOpenAISecretToAgent(): Promise<void> {
  const key = currentOpenAIKey();
  if (key === null) {
    return;
  }
  try {
    await sendRequest(
      "settings.secret",
      "settings.secret.changed",
      { openai_api_key: key }
    );
  } catch (error) {
    appendRuntimeLog(
      "desktop.log",
      "Unable to sync provider secret to Agent: " + String(error)
    );
  }
}

function appendRuntimeLog(fileName: string, message: string): void {
  try {
    const directory = logDirectory();
    appendBoundedLog(directory,fileName,message,[sessionOpenAIKey||'',...Object.values(modelCredentials||{}),
      ...Object.values(sessionMcpSecrets).flatMap(values=>Object.values(values)),process.env.LCA_OPENAI_API_KEY||'']);
  } catch (error) {
    console.error("[desktop] Unable to write runtime log", error);
  }
}

function broadcastAgentEvent(event: AgentEnvelope): void {
  for (const window of BrowserWindow.getAllWindows()) {
    window.webContents.send("agent:event", event);
  }
}

function rejectPending(reason: string): void {
  for (const [requestId, item] of pending) {
    clearTimeout(item.timer);
    item.reject(new Error(reason));
    pending.delete(requestId);
  }
}

function handleAgentMessage(raw: WebSocket.RawData): void {
  let event: AgentEnvelope;

  try {
    event = JSON.parse(raw.toString("utf8")) as AgentEnvelope;
  } catch (error) {
    console.error("[desktop] Invalid Agent WebSocket JSON", error);
    return;
  }

  broadcastAgentEvent(event);

  const requestId = event.request_id;
  if (!requestId) {
    return;
  }

  const item = pending.get(requestId);
  if (!item) {
    return;
  }

  if (event.type === "error") {
    clearTimeout(item.timer);
    pending.delete(requestId);
    item.reject(new Error(String(event.payload?.message ?? "Agent request failed")));
    return;
  }

  if (event.type === item.expectedType) {
    clearTimeout(item.timer);
    pending.delete(requestId);
    item.resolve(event);
  }
}

function connectAgentWebSocket(ready: {
  host: string;
  port: number;
  token: string;
  version: string;
  protocol: string;
}, reconnectAttempt = 0): void {
  agentSocket?.close();

  const socket = new WebSocket("ws://" + ready.host + ":" + ready.port + "/ws", {
    headers: {
      Authorization: "Bearer " + ready.token
    }
  });
  agentSocket = socket;

  socket.on("open", () => {
    agentStatus = {
      state: "ready",
      host: ready.host,
      port: ready.port,
      version: ready.version,
      protocol: ready.protocol
    };
    console.log("[desktop] Agent WebSocket connected");
    broadcastAgentEvent({type:"connection.restored",payload:{reconnectAttempt}});

    lastAgentReady = {
      host: ready.host,
      port: ready.port,
      version: ready.version,
      protocol: ready.protocol
    };
    maybeCompletePackagedSmoke();
    void syncOpenAISecretToAgent();
    void syncMcpSecretsToAgent();
    void syncModelCredentials().catch(() => appendRuntimeLog("desktop.log", "Protected model credential synchronization failed; check Settings."));
  });

  socket.on("message", handleAgentMessage);

  socket.on("error", (error) => {
    console.error("[desktop] Agent WebSocket error", error);
    if (!shuttingDown) {
      agentStatus = {
        state: "error",
        host: ready.host,
        port: ready.port,
        version: ready.version,
        protocol: ready.protocol,
        error: String(error)
      };
    }
  });

  socket.on("close", () => {
    if (agentSocket !== socket) return;
    rejectPending("Agent WebSocket disconnected.");
    if (!shuttingDown && agentProcess) {
      agentStatus = {
        state: "error",
        host: ready.host,
        port: ready.port,
        version: ready.version,
        protocol: ready.protocol,
        error: "Agent WebSocket disconnected."
      };
      if (reconnectAttempt < 8) setTimeout(() => {
        if (!shuttingDown && agentProcess && agentSocket === socket)
          connectAgentWebSocket(ready, reconnectAttempt + 1);
      }, Math.min(1000 * 2 ** reconnectAttempt, 10000));
    }
  });
}

function updateFromAgentStdout(chunk: Buffer): void {
  stdoutBuffer += chunk.toString("utf8");
  const lines = stdoutBuffer.split(/\r?\n/);
  stdoutBuffer = lines.pop() ?? "";

  for (const line of lines) {
    if (!line.startsWith("LCA_AGENT_READY ")) {
      if (line.trim()) {
        console.log("[agent]", line);
        appendRuntimeLog("agent.log", "[stdout] " + line);
      }
      continue;
    }

    try {
      const ready = JSON.parse(line.slice("LCA_AGENT_READY ".length)) as {
        host: string;
        port: number;
        token: string;
        version: string;
        protocol: string;
      };
      const compatibility = checkProtocolCompatibility(ready.protocol);
      if (!compatibility.compatible) {
        const message =
          compatibility.reason ??
          "Agent protocol is not supported by this Desktop build.";
        agentStatus = {
          state: "error",
          host: ready.host,
          port: ready.port,
          version: ready.version,
          protocol: ready.protocol,
          error: message
        };
        appendRuntimeLog("desktop.log", message);
        agentProcess?.kill();
        return;
      }
      agentToken = ready.token;
      agentStatus = {
        state: "starting",
        host: ready.host,
        port: ready.port,
        version: ready.version,
        protocol: ready.protocol
      };
      appendRuntimeLog(
        "desktop.log",
        "Agent ready on " + ready.host + ":" + ready.port + " protocol=" + ready.protocol
      );
      connectAgentWebSocket(ready);
    } catch (error) {
      agentStatus = {
        state: "error",
        error: "Invalid Agent ready payload: " + String(error)
      };
    }
  }
}

function launchAgent(
  command: string,
  args: string[],
  cwd: string,
  virtualEnv?: string
): ChildProcessWithoutNullStreams {
  const environment: NodeJS.ProcessEnv = {
    ...process.env,
    PYTHONUNBUFFERED: "1",
    LCA_DATA_DIR: process.env.LCA_DATA_DIR || app.getPath("userData"),
    LCA_DESKTOP_DATA_DIR: app.getPath("userData")
  };
  if (virtualEnv) {
    environment.VIRTUAL_ENV = virtualEnv;
  }
  if (
    /(?:^|[\\/])python(?:3)?(?:\.exe)?$/i.test(command)
  ) {
    environment.LCA_AGENT_PYTHON = command;
  }

  appendRuntimeLog(
    "desktop.log",
    "Launching Agent command=" + command + " cwd=" + cwd
  );

  const child = spawn(
    command,
    args,
    {
      cwd,
      env: environment,
      windowsHide: true
    }
  );

  child.stdout.on("data", updateFromAgentStdout);
  child.stderr.on("data", (chunk: Buffer) => {
    const message = chunk.toString("utf8").trimEnd();
    console.error("[agent:stderr]", message);
    if (message) {
      appendRuntimeLog("agent.log", "[stderr] " + message);
    }
  });
  child.on("exit", (code, signal) => {
    agentProcess = null;
    agentToken = null;
    agentSocket = null;
    rejectPending("Agent process exited.");
    appendRuntimeLog(
      "desktop.log",
      "Agent exited code=" + code + " signal=" + signal
    );
    if (!shuttingDown) {
      agentStatus = {
        state: code === 0 ? "stopped" : "error",
        error: code === 0 ? undefined : "Agent exited with code=" + code + ", signal=" + signal
      };
    }
  });

  return child;
}

function startAgent(): void {
  agentStatus = { state: "starting" };

  const configuredAgent = process.env.LCA_AGENT_EXECUTABLE;
  if (configuredAgent) {
    if (!existsSync(configuredAgent)) {
      agentStatus = {
        state: "error",
        error: "Configured Agent executable was not found: " + configuredAgent
      };
      return;
    }
    agentProcess = launchAgent(
      configuredAgent,
      ["--port", "0", "--data-service"],
      path.dirname(configuredAgent)
    );
  } else if (app.isPackaged) {
    const bundledAgent = packagedAgentPath();
    if (!existsSync(bundledAgent)) {
      const message = "Bundled Agent executable is missing: " + bundledAgent;
      agentStatus = {
        state: "error",
        error: message
      };
      appendRuntimeLog("desktop.log", message);
      return;
    }
    agentProcess = launchAgent(
      bundledAgent,
      ["--port", "0", "--data-service"],
      path.dirname(bundledAgent)
    );
  } else {
    const configuredPython = process.env.LCA_PYTHON;
    const python = configuredPython || projectPythonPath();

    if (!configuredPython && !existsSync(python)) {
      agentStatus = {
        state: "error",
        error: "Project .venv is missing. Run .\\scripts\\dev\\bootstrap.ps1 first."
      };
      return;
    }

    console.log("[desktop] Agent Python: " + python);
    agentProcess = launchAgent(
      python,
      ["-m", "agent.server.main", "--port", "0", "--data-service"],
      repoRoot(),
      path.join(repoRoot(), ".venv")
    );
  }

  agentProcess.once("error", (error) => {
    const message = "Unable to start Agent process: " + String(error);
    appendRuntimeLog("desktop.log", message);
    agentStatus = {
      state: "error",
      error: message
    };
  });
}

function sendRequest(
  type: string,
  expectedType: string,
  payload: Record<string, unknown> = {},
  ids: { threadId?: string; turnId?: string } = {},
  timeoutMs = 15000
): Promise<AgentEnvelope> {
  const socket = agentSocket;
  if (!socket || socket.readyState !== WebSocket.OPEN) {
    return Promise.reject(new Error("Agent WebSocket is not connected."));
  }

  const requestId = "req_" + randomUUID().replace(/-/g, "");
  const message: AgentEnvelope = {
    type,
    request_id: requestId,
    thread_id: ids.threadId,
    turn_id: ids.turnId,
    timestamp: new Date().toISOString(),
    payload
  };

  return new Promise<AgentEnvelope>((resolve, reject) => {
    const timer = setTimeout(() => {
      pending.delete(requestId);
      reject(new Error("Agent request timed out: " + type));
    }, timeoutMs);

    pending.set(requestId, {
      expectedType,
      resolve,
      reject,
      timer
    });

    socket.send(JSON.stringify(message), (error) => {
      if (error) {
        clearTimeout(timer);
        pending.delete(requestId);
        reject(error);
      }
    });
  });
}

async function stopAgent(): Promise<void> {
  shuttingDown = true;
  rejectPending("Application is closing.");

  const current = agentProcess;
  const currentPort = agentStatus.port;
  const currentToken = agentToken;

  if (agentSocket) {
    agentSocket.close();
    agentSocket = null;
  }

  if (!current) {
    return;
  }

  if (currentPort && currentToken) {
    try {
      await fetch("http://127.0.0.1:" + currentPort + "/shutdown", {
        method: "POST",
        signal: AbortSignal.timeout(2000),
        headers: {
          Authorization: "Bearer " + currentToken
        }
      });
    } catch {
      // Best-effort graceful shutdown; force kill below if still alive.
    }
  }

  if (current.exitCode === null) {
    await Promise.race([
      new Promise<void>((resolve) => {
        current.once("exit", () => resolve());
      }),
      new Promise<void>((resolve) => {
        setTimeout(resolve, 1500);
      })
    ]);
  }

  if (current.exitCode === null) {
    appendRuntimeLog("desktop.log", "Agent did not stop gracefully; forcing termination.");
    current.kill();
    await Promise.race([
      new Promise<void>((resolve) => {
        current.once("exit", () => resolve());
      }),
      new Promise<void>((resolve) => {
        setTimeout(resolve, 700);
      })
    ]);
  }
}

function createWindow(): void {
  rendererReady = false;
  const workArea = screen.getPrimaryDisplay().workArea;
  mainWindow = new BrowserWindow({
    show: process.env.LCA_HEADLESS_SMOKE !== "1",
    width: Math.min(1180, workArea.width),
    height: Math.min(780, workArea.height),
    minWidth: Math.min(900, workArea.width),
    minHeight: Math.min(600, workArea.height),
    backgroundColor: "#1a2225",
    ...(process.platform === "win32" || process.platform === "linux" ? {
      titleBarStyle: "hidden" as const,
      titleBarOverlay: {color:"#1a2225", symbolColor:"#ffffff", height:44}
    } : {}),
    webPreferences: {
      offscreen: process.env.LCA_HEADLESS_SMOKE === "1",
      backgroundThrottling: process.env.LCA_HEADLESS_SMOKE !== "1",
      preload: path.join(__dirname, "preload.js"),
      contextIsolation: true,
      nodeIntegration: false
    }
  });
  // The renderer's header and native window buttons share one row.
  mainWindow.setMenu(null);

  mainWindow.webContents.on("did-finish-load", () => {
    appendRuntimeLog(
      "renderer.log",
      "did-finish-load url=" + mainWindow?.webContents.getURL()
    );
  });

  mainWindow.webContents.on(
    "did-fail-load",
    (_event, errorCode, errorDescription, validatedURL) => {
      appendRuntimeLog(
        "renderer.log",
        "did-fail-load code=" +
          errorCode +
          " description=" +
          errorDescription +
          " url=" +
          validatedURL
      );
    }
  );

  mainWindow.webContents.on("render-process-gone", (_event, details) => {
    appendRuntimeLog(
      "renderer.log",
      "render-process-gone reason=" +
        details.reason +
        " exitCode=" +
        details.exitCode
    );
  });

  mainWindow.webContents.on("unresponsive", () => {
    appendRuntimeLog("renderer.log", "renderer unresponsive");
  });

  const devUrl = process.env.VITE_DEV_SERVER_URL;
  if (devUrl) {
    void mainWindow.loadURL(devUrl).catch((error) => {
      appendRuntimeLog("renderer.log", "loadURL failed: " + String(error));
    });
  } else {
    const indexPath = path.join(__dirname, "..", "dist", "index.html");
    appendRuntimeLog("renderer.log", "Loading packaged renderer: " + indexPath);
    void mainWindow.loadFile(indexPath).catch((error) => {
      appendRuntimeLog("renderer.log", "loadFile failed: " + String(error));
    });
  }
}

ipcMain.on("renderer:ready", () => {
  rendererReady = true;
  appendRuntimeLog("renderer.log", "Renderer React root mounted successfully.");
  maybeCompletePackagedSmoke();
});

let runtimeUpdater:OpenCodeUpdateManager | undefined;
const openCodeRuntime = new OpenCodeRuntime(() => runtimeUpdater?.current());
type OpenCodeTurn = {
  controller: AbortController;
  sessionId?: string;
  cancelled: boolean;
  outcome: string;
  threadId: string;
  goal: string;
  projectId?: string;
  done: Promise<void>;
  appended: Set<string>;
  taskId?:string;
  pauseTask?:boolean;
  verifying?:boolean;
};
type OpenCodeTask = {
  id:string;
  workspace:string;
  goal:string;
  opencode_local_only?:boolean;
  verification?: Array<{ok:boolean;summary?:string}>;
  config:{roles?: {executor?:{model_profile_id?:string}}; budget?:Record<string,number|null>};
};
const activeOpenCodeTurns = new Map<string, OpenCodeTurn>();
let preparingOpenCodeTask = false;
const pendingOpenCodeApprovals = new Map<string, { sessionId: string; requestId: string; turnId: string; threadId: string; action:string; resources:string[]; sensitive:boolean }>();
ipcMain.handle("agent:engine-status", () => {
  if (openCodeRuntime.bundledVersion()) installedRuntimeUpdater();
  const status = openCodeRuntime.status();
  return { selected: "opencode", engines: [{ id: "opencode", ...status }] };
});
function installedRuntimeUpdater() {
  const bundled = openCodeRuntime.bundledVersion();
  if (!bundled) throw new Error("内置 OpenCode 运行时缺失");
  return runtimeUpdater ??= new OpenCodeUpdateManager(app.getPath("userData"),bundled,probeOpenCodeCompatibility,
    ()=>preparingOpenCodeTask || activeOpenCodeTurns.size > 0 || quitInProgress);
}
ipcMain.handle("agent:engine-update-check", async () => {
  const manager = installedRuntimeUpdater();
  const offer = await manager.checkForUpdates();
  return {current:manager.current().version,latest:offer?.version ?? null};
});
ipcMain.handle("agent:engine-update-install", async () => {
  const manager = installedRuntimeUpdater();
  if (preparingOpenCodeTask || activeOpenCodeTurns.size) throw new Error("请先停止当前执行");
  const offer = await manager.checkForUpdates();
  if (!offer) throw new Error("没有可用的独立运行时升级");
  const decision = await dialog.showMessageBox({type:"question",buttons:["取消","校验并升级"],defaultId:0,cancelId:0,
    title:"升级 OpenCode 运行时",message:`独立安装 OpenCode ${offer.version}？`,detail:"验证 SHA256 和运行协议后切换，原版本和应用历史保留。"});
  if (decision.response !== 1) return {current:manager.current().version};
  try {
    const active = await manager.upgrade(offer,()=>openCodeRuntime.stop());
    appendRuntimeLog("desktop.log","OpenCode runtime version activated "+active.version);
    return {current:active.version};
  } catch (error) {
    appendRuntimeLog("desktop.log","OpenCode runtime upgrade failed; current version was retained");
    throw error;
  }
});
ipcMain.handle("agent:engine-update-restore", async () => {
  const manager = installedRuntimeUpdater();
  const decision = await dialog.showMessageBox({type:"question",buttons:["取消","回到内置版本"],defaultId:0,cancelId:0,
    title:"回到内置 OpenCode",message:"切换为应用附带的锁定运行时？"});
  if (decision.response !== 1) return {current:manager.current().version};
  const active = await manager.restoreBundled(()=>openCodeRuntime.stop());
  appendRuntimeLog("desktop.log","OpenCode restored to "+active.version);
  return {current:active.version};
});
ipcMain.handle("agent:get-status", () => agentStatus);
ipcMain.handle("agent:screenshot-preview", (_event, candidate: unknown) =>
  desktopArtifact(process.env.LCA_DATA_DIR || app.getPath("userData"), candidate));
ipcMain.handle("agent:update-check", async () => {
  try{const offer=await installedUpdater().check();return {ok:true,checked_at:new Date().toISOString(),current_version:app.getVersion(),latest_version:offer?.version||app.getVersion(),update_available:!!offer,release_url:'https://github.com/yunfei00/local-coding-agent/releases',automatic:false,can_auto_download:false,can_auto_install:false};}
  catch(error){return {ok:false,checked_at:new Date().toISOString(),current_version:app.getVersion(),update_available:false,error:String(error),automatic:false,can_auto_download:false,can_auto_install:false};}
});
let updateManager:UpdateManager|undefined;
function installedUpdater(){
  if(process.platform!=='win32'||process.arch!=='x64')throw new Error('更新下载仅支持 Windows x64');
  return updateManager ||=new UpdateManager(app.getPath('userData'),app.getVersion(),undefined,undefined,{portable:!!process.env.PORTABLE_EXECUTABLE_DIR,emit:state=>{if(mainWindow&&!mainWindow.isDestroyed()&&!mainWindow.webContents.isDestroyed())mainWindow.webContents.send('update:state',state);}});
}
ipcMain.handle('agent:environment',()=>sendRequest('maintenance.environment','maintenance.loaded'));
ipcMain.handle('agent:data-backup',()=>sendRequest('maintenance.backup','maintenance.loaded'));
ipcMain.handle('agent:update-state',()=>installedUpdater().status());
ipcMain.handle('agent:update-cancel',()=>{installedUpdater().cancel();return {cancelled:true};});
ipcMain.handle('agent:update-open-package',()=>installedUpdater().openPackage(file=>shell.openPath(file)));
ipcMain.handle('agent:update-open-folder',()=>installedUpdater().openFolder(file=>shell.showItemInFolder(file)));
ipcMain.handle('agent:update-download',async()=>{
  const manager=installedUpdater();const offer=await manager.check();
  if(!offer)throw new Error('当前没有可用更新');
  const choice=await dialog.showMessageBox({type:'question',buttons:['取消','下载并校验'],defaultId:0,cancelId:0,
    title:'下载更新',message:`下载 Windows x64 版本 ${offer.version}？`,detail:offer.notes.slice(0,3000)||'下载后不会自动安装。'});
  if(choice.response!==1)throw new Error('已取消下载');
  return manager.downloadUpdate(offer.version);
});
ipcMain.handle('agent:update-install',async()=>{
  throw new Error('已采用手动更新方案。请下载校验后主动打开安装包；软件不会自动退出或安装。');
});
ipcMain.handle(
  "agent:update-open-release",
  async (_event, url: string) => {
    const value = String(url ?? "");
    if (!value.startsWith("https://github.com/yunfei00/local-coding-agent/")) {
      throw new Error("Unsupported release URL.");
    }
    await shell.openExternal(value);
    return { ok: true };
  }
);

ipcMain.handle("agent:diagnostics-get", async () => {
  const event = await sendRequest(
    "diagnostics.get",
    "diagnostics.loaded"
  );
  return {
    event,
    desktop: {
      app_version: app.getVersion(),
      packaged: app.isPackaged,
      platform: process.platform,
      architecture: process.arch,
      electron: process.versions.electron,
      chrome: process.versions.chrome,
      node: process.versions.node,
      secret_storage: secretStorageStatus().mode
    }
  };
});
ipcMain.handle(
  "clipboard:copy-text",
  async (_event, text: string) => {
    if (typeof text !== "string" || text.length > 2_000_000) throw new Error("Clipboard text is too large");
    clipboard.writeText(text);
    return {ok: true};
  }
);
ipcMain.handle(
  "agent:diagnostics-copy",
  async (_event, report: string) => {
    clipboard.writeText(String(report ?? ""));
    return { ok: true };
  }
);

ipcMain.handle("agent:settings-get", async () => {
  const event = await sendRequest("settings.get", "settings.loaded");
  return {
    event,
    secret: secretStorageStatus()
  };
});
ipcMain.handle(
  "agent:settings-apply",
  async (
    _event,
    settings: Record<string, unknown>,
    secretUpdate?: {
      action?: "keep" | "set" | "clear";
      value?: string;
    }
  ) => {
    const event = await sendRequest(
      "settings.apply",
      "settings.changed",
      { settings }
    );

    const action = secretUpdate?.action ?? "keep";
    let secret = secretStorageStatus();
    if (action === "set") {
      secret = saveOpenAIKey(String(secretUpdate?.value ?? ""));
      await sendRequest(
        "settings.secret",
        "settings.secret.changed",
        { openai_api_key: currentOpenAIKey() ?? "" }
      );
    } else if (action === "clear") {
      secret = saveOpenAIKey("");
      await sendRequest(
        "settings.secret",
        "settings.secret.changed",
        { openai_api_key: "" }
      );
    } else {
      const key = currentOpenAIKey();
      if (key !== null) {
        await sendRequest(
          "settings.secret",
          "settings.secret.changed",
          { openai_api_key: key }
        );
      }
    }

    const provider = await sendRequest("model.list", "model.listed");
    return { event, provider, secret };
  }
);
ipcMain.handle("agent:settings-reset", async () => {
  const event = await sendRequest(
    "settings.reset",
    "settings.changed"
  );
  const key = currentOpenAIKey();
  if (key !== null) {
    await sendRequest(
      "settings.secret",
      "settings.secret.changed",
      { openai_api_key: key }
    );
  }
  const provider = await sendRequest("model.list", "model.listed");
  return {
    event,
    provider,
    secret: secretStorageStatus()
  };
});
ipcMain.handle(
  "agent:prompt-rules-get",
  async (_event, threadId?: string) => {
    return sendRequest(
      "prompt_rules.get",
      "prompt_rules.loaded",
      threadId ? { thread_id: threadId } : {},
      threadId ? { threadId } : {}
    );
  }
);
ipcMain.handle(
  "agent:prompt-rule-set",
  async (
    _event,
    scope: string,
    content: string,
    enabled: boolean,
    projectId?: string,
    threadId?: string
  ) => {
    return sendRequest(
      "prompt_rules.set",
      "prompt_rules.changed",
      {
        scope,
        content,
        enabled,
        ...(projectId ? { project_id: projectId } : {}),
        ...(threadId ? { thread_id: threadId } : {})
      },
      threadId ? { threadId } : {}
    );
  }
);
ipcMain.handle(
  "agent:prompt-rule-toggle",
  async (
    _event,
    scope: string,
    enabled: boolean,
    projectId?: string,
    threadId?: string
  ) => {
    return sendRequest(
      "prompt_rules.toggle",
      "prompt_rules.changed",
      {
        scope,
        enabled,
        ...(projectId ? { project_id: projectId } : {}),
        ...(threadId ? { thread_id: threadId } : {})
      },
      threadId ? { threadId } : {}
    );
  }
);
ipcMain.handle(
  "agent:prompt-rule-reset",
  async (
    _event,
    scope: string,
    projectId?: string,
    threadId?: string
  ) => {
    return sendRequest(
      "prompt_rules.reset",
      "prompt_rules.changed",
      {
        scope,
        ...(projectId ? { project_id: projectId } : {}),
        ...(threadId ? { thread_id: threadId } : {})
      },
      threadId ? { threadId } : {}
    );
  }
);

ipcMain.handle("agent:mcp-list", async () => {
  const event = await sendRequest("mcp.list", "mcp.listed");
  return {
    event,
    secrets: mcpSecretStatuses()
  };
});
ipcMain.handle(
  "agent:mcp-upsert",
  async (
    _event,
    server: Record<string, unknown>,
    secretUpdate?: {
      action?: "keep" | "set" | "clear";
      values?: Record<string, string>;
    }
  ) => {
    const event = await sendRequest(
      "mcp.upsert",
      "mcp.changed",
      { server },
      {},
      45_000
    );
    const serverPayload = event.payload?.server;
    const serverId =
      serverPayload && typeof serverPayload === "object"
        ? String((serverPayload as Record<string, unknown>).id ?? "")
        : "";
    if (serverId) {
      updateMcpSecrets(
        serverId,
        secretUpdate?.action ?? "keep",
        secretUpdate?.values
      );
      await syncMcpSecretsToAgent();
    }
    const listed = await sendRequest("mcp.list", "mcp.listed");
    return {
      event: listed,
      secrets: mcpSecretStatuses()
    };
  }
);
ipcMain.handle(
  "agent:mcp-delete",
  async (_event, serverId: string) => {
    const id = String(serverId ?? "");
    const event = await sendRequest(
      "mcp.delete",
      "mcp.changed",
      { server_id: id },
      {},
      45_000
    );
    updateMcpSecrets(id, "clear");
    return {
      event,
      secrets: mcpSecretStatuses()
    };
  }
);
ipcMain.handle("agent:mcp-refresh", async () => {
  await syncMcpSecretsToAgent();
  const event = await sendRequest(
    "mcp.refresh",
    "mcp.refreshed",
    {},
    {},
    45_000
  );
  return {
    event,
    secrets: mcpSecretStatuses()
  };
});

ipcMain.handle(
  "agent:context-get",
  async (_event, threadId: string) => {
    return sendRequest(
      "context.get",
      "context.loaded",
      { thread_id: threadId },
      { threadId }
    );
  }
);
ipcMain.handle(
  "agent:context-pin",
  async (_event, threadId: string, pathValue: string) => {
    return sendRequest(
      "context.pin",
      "context.changed",
      { thread_id: threadId, path: pathValue },
      { threadId }
    );
  }
);
ipcMain.handle(
  "agent:context-unpin",
  async (_event, threadId: string, pathValue: string) => {
    return sendRequest(
      "context.unpin",
      "context.changed",
      { thread_id: threadId, path: pathValue },
      { threadId }
    );
  }
);
ipcMain.handle(
  "agent:context-refresh",
  async (_event, threadId: string) => {
    return sendRequest(
      "context.refresh",
      "context.changed",
      { thread_id: threadId },
      { threadId },
      45_000
    );
  }
);

ipcMain.handle("agent:git-overview", async () => {
  return sendRequest("git.overview", "git.loaded");
});
ipcMain.handle(
  "agent:git-worktree-open",
  async (_event, pathValue: string, model?: string) => {
    return sendRequest(
      "git.worktree.open",
      "project.opened",
      model
        ? { path: pathValue, model }
        : { path: pathValue },
      {},
      45_000
    );
  }
);

ipcMain.handle("agent:permission-get", async () => {
  return sendRequest("permission.get", "permission.loaded");
});
ipcMain.handle("agent:permission-set", async (_event, mode: string, options: {scope?:string;target?:string}={}) => {
  if (activeOpenCodeTurns.size) throw new Error("请先停止 OpenCode 执行，再修改权限。");
  let confirmed=false;
  if(mode==='full_access') {
    const current=await sendRequest('permission.get','permission.loaded');
    const grant=current.payload?.authorization as {full_access_confirmed?:boolean}|undefined;
    if(!grant?.full_access_confirmed) {
      const answer=await dialog.showMessageBox({type:'warning',buttons:['取消','启用完全访问'],defaultId:0,cancelId:0,
        title:'启用完全访问',message:'允许 Agent 在当前 Windows 用户权限下连续操作文件、终端、Git、MCP 和桌面窗口。',
        detail:'此授权可持久保存并随时撤销；普通操作不再逐项确认。窗口控件与脱敏截图可能发送至本任务配置的模型服务。不会取得管理员权限或绕过 UAC。高风险、凭据外传、系统保护和远程发布仍受限制。'});
      if(answer.response!==1)throw new Error('未启用完全访问');
      confirmed=true;
    }
  }
  return sendRequest("permission.set", "permission.changed", { mode,scope:options.scope||'global',target:options.target,confirm_full_access:confirmed });
});
ipcMain.handle(
  "agent:approval-respond",
  async (
    _event,
    approvalId: string,
    decision: "allow_once" | "allow_turn" | "deny",
    turnId?: string
  ) => {
    const pending = pendingOpenCodeApprovals.get(approvalId);
    if (pending) {
      const entry = activeOpenCodeTurns.get(pending.turnId);
      if (!entry || entry.controller.signal.aborted || (turnId && turnId !== pending.turnId)) throw new Error("审批对应的执行已结束");
      if (decision !== "deny" && decision !== "allow_once" && decision !== "allow_turn") throw new Error("无效审批决定");
      pendingOpenCodeApprovals.delete(approvalId);
      try {
        if (pending.sensitive) decision = "deny";
        if (decision !== "deny" && ["shell","bash"].includes(pending.action)) {
          try {
            await sendRequest("task.external.shell_check", "task.loaded", {project_id:entry.projectId,task_id:entry.taskId,
              goal:entry.goal,commands:pending.resources},{threadId:entry.threadId});
          } catch {
            decision = "deny";
          }
        }
        entry.controller.signal.throwIfAborted();
        await openCodeRuntime.replyPermission(pending.sessionId, pending.requestId, decision === "deny" ? "reject" : "once");
      } catch (error) {
        if (!entry.controller.signal.aborted) pendingOpenCodeApprovals.set(approvalId, pending);
        throw error;
      }
      broadcastAgentEvent({ type: "approval.resolved", request_id: "req_" + randomUUID().replace(/-/g, ""), turn_id: pending.turnId, thread_id: pending.threadId, timestamp: new Date().toISOString(), payload: { approval_id: approvalId, decision, engine: "opencode" } });
      return { type: "approval.resolved", request_id: "req_" + randomUUID().replace(/-/g, ""), turn_id: pending.turnId, thread_id: pending.threadId, timestamp: new Date().toISOString(), payload: { approval_id: approvalId, decision } };
    }
    return sendRequest(
      "approval.respond",
      "approval.resolved",
      { approval_id: approvalId, decision },
      turnId ? { turnId } : {}
    );
  }
);
ipcMain.handle("agent:project-open", async (_event, model?: string) => {
  const selection = await dialog.showOpenDialog({
    properties: ["openDirectory"],
    title: "Open coding workspace"
  });
  if (selection.canceled || !selection.filePaths[0]) {
    return { canceled: true };
  }
  const event = await sendRequest(
    "project.open",
    "project.opened",
    model
      ? { path: selection.filePaths[0], model, defer_thread:true }
      : { path: selection.filePaths[0], defer_thread:true }
  );
  return { canceled: false, event };
});
ipcMain.handle("agent:project-create-defaults", () => ({parent_path: app.getPath("documents")}));
ipcMain.handle("agent:project-choose-parent", async (_event, defaultPath?: string) => {
  const selected = await dialog.showOpenDialog({
    title:"Choose project location", properties:["openDirectory", "createDirectory"],
    defaultPath: typeof defaultPath === "string" ? defaultPath : app.getPath("documents")
  });
  return {canceled:selected.canceled, path:selected.filePaths[0]};
});
ipcMain.handle("agent:project-create", async (_event, options: Record<string, unknown>) =>
  sendRequest("project.create", "project.opened", {...options, defer_thread:true}, {}, 30000));
ipcMain.handle("agent:project-get", async () => {
  return sendRequest("project.get", "project.loaded");
});
ipcMain.handle("window:theme", (_event, theme:unknown) => {
  if (theme !== "light" && theme !== "dark") throw new Error("Invalid window theme");
  const color = theme === "light" ? "#ecf6f9" : "#1a2225";
  mainWindow?.setBackgroundColor(color);
  if (process.platform === "win32" || process.platform === "linux") {
    mainWindow?.setTitleBarOverlay({color, symbolColor:theme === "light" ? "#1a1c1e" : "#ffffff", height:44});
  }
});
ipcMain.handle("window:menu-action", async (_event, action:unknown) => {
  const contents = mainWindow?.webContents;
  if (!contents || contents.isDestroyed()) return;
  // Fixed native editing/view actions only; no arbitrary command or renderer path.
  switch (action) {
    case "undo": contents.undo(); break;
    case "redo": contents.redo(); break;
    case "cut": contents.cut(); break;
    case "copy": contents.copy(); break;
    case "paste": contents.paste(); break;
    case "selectAll": contents.selectAll(); break;
    case "zoomIn": contents.setZoomFactor(Math.min(2, contents.getZoomFactor() + .1)); break;
    case "zoomOut": contents.setZoomFactor(Math.max(.5, contents.getZoomFactor() - .1)); break;
    case "zoomReset": contents.setZoomFactor(1); break;
    case "guide": await shell.openExternal("https://github.com/yunfei00/local-coding-agent/blob/main/docs/v0.4/user-guide.md"); break;
    case "about": await dialog.showMessageBox(mainWindow!, {type:"info", title:"Local Coding Agent", message:"Local Coding Agent", detail:"Version " + app.getVersion()}); break;
    case "quit": app.quit(); break;
    default: throw new Error("Unsupported menu action");
  }
});
async function openRegisteredProjectFolder(projectId?:string) {
  // Resolve a registered backend project, never an arbitrary renderer path.
  if (projectId !== undefined && (typeof projectId !== "string" || !projectId)) throw new Error("Invalid project ID");
  const event = await sendRequest("project.get", "project.loaded", projectId ? {project_id:projectId} : {});
  const project = event.payload?.project as {id?:unknown; path?:unknown} | undefined;
  if (projectId && project?.id !== projectId) throw new Error("Project identity mismatch; fully restart the updated app and backend.");
  if (typeof project?.path !== "string" || !path.isAbsolute(project.path)) throw new Error("No active project folder");
  const error = await shell.openPath(project.path);
  if (error) throw new Error(error);
}
ipcMain.handle("agent:project-diff",async(event)=>{
  if(event.sender!==mainWindow?.webContents)throw new Error("Invalid sender");
  const result=await sendRequest("project.get","project.loaded");
  const project=result.payload?.project as {path?:unknown}|undefined;
  if(typeof project?.path!=="string"||!path.isAbsolute(project.path))throw new Error("No active project");
  return readProjectDiff(project.path);
});
let projectSearchController:AbortController|undefined;
ipcMain.handle("agent:project-search-cancel",()=>projectSearchController?.abort());
ipcMain.handle("agent:project-search",async(event,query:unknown,mode:unknown)=>{
  if(event.sender!==mainWindow?.webContents)throw new Error("Invalid sender");
  if(typeof query!=="string"||(mode!=="file"&&mode!=="text"))throw new Error("Invalid search");
  if(projectSearchController)throw new Error("Search already active");
  const controller=new AbortController();projectSearchController=controller;
  const abort=()=>controller.abort();event.sender.once("destroyed",abort);
  try{
    const result=await sendRequest("project.get","project.loaded");
    const project=result.payload?.project as {path?:unknown}|undefined;
    if(typeof project?.path!=="string"||!path.isAbsolute(project.path))throw new Error("No active project");
    return await searchProject(project.path,query,mode,controller.signal);
  }finally{event.sender.removeListener("destroyed",abort);projectSearchController=undefined;}
});
ipcMain.handle("agent:project-folder", () => openRegisteredProjectFolder());
ipcMain.handle("agent:project-folder-by-id", (_event, projectId:string) => {
  if (typeof projectId !== "string" || !projectId) throw new Error("Invalid project ID");
  return openRegisteredProjectFolder(projectId);
});
ipcMain.handle("agent:project-list", async () => {
  return sendRequest("project.list", "project.listed");
});
ipcMain.handle("agent:project-remove", async (_event, projectId:string) => {
  if (typeof projectId !== "string" || !projectId) throw new Error("Invalid project ID");
  return sendRequest("project.remove", "project.removed", {project_id:projectId});
});
ipcMain.handle(
  "agent:project-select",
  async (_event, projectId: string, model?: string) => {
    return sendRequest(
      "project.select",
      "project.selected",
      model ? { project_id: projectId, model, defer_thread:true } : { project_id: projectId, defer_thread:true }
    );
  }
);
ipcMain.handle("agent:model-list", async () => {
  return sendRequest("model.list", "model.listed");
});
ipcMain.handle("agent:model-select", async (_event, threadId: string, model: string) => {
  return sendRequest("model.select", "model.selected", { model }, { threadId });
});
ipcMain.handle("agent:thread-create", async (_event, model?: string, initialPrompt?: string) => {
  return sendRequest(
    "thread.create",
    "thread.created",
    {model, initial_prompt:initialPrompt}
  );
});
ipcMain.handle("agent:thread-list", async () => {
  return sendRequest("thread.list", "thread.listed");
});
ipcMain.handle("agent:task-request", async (_event, threadId: string, operation: string, payload: Record<string, unknown> = {}) => {
  if (operation === "task.credential.status") return {type:"task.loaded", payload:{configured:Object.keys(readModelCredentials()), mode:safeStorage.isEncryptionAvailable() ? "os_protected" : "session_only"}};
  if (operation === "task.credential.set") {
    const id = String(payload.connection_id ?? "");
    const key = payload.api_key;
    if (!/^[A-Za-z0-9_-]{1,100}$/.test(id) || typeof key !== "string" || key.length > 16000) throw new Error("Invalid connection credential");
    const values = {...readModelCredentials()};
    if (key) values["connection-" + id] = key; else delete values["connection-" + id];
    // Agent rejects changes while a turn is running before disk persistence.
    await sendRequest("task.credentials.update", "task.loaded", {credentials:values});
    storeModelCredentials(values);
    return {type:"task.loaded", payload:{mode:safeStorage.isEncryptionAvailable() ? "os_protected" : "session_only", configured:!!key}};
  }
  const allowed = new Set(["task.runtime.list", "task.catalog.get", "task.catalog.update", "task.settings.get", "task.settings.update", "task.connection.test", "task.list", "task.start", "task.resume", "task.continue", "task.pause", "task.cancel", "task.budget.add", "task.configure", "task.approve", "task.diagnostics"]);
  allowed.add("task.runtime.diagnostics");
  allowed.add('task.append'); allowed.add('task.runtime.events');
  allowed.add("task.model.diagnostic"); allowed.add("task.model.diagnostic.cancel");
  for(const operation of ['knowledge.get','knowledge.search','knowledge.save','knowledge.delete','knowledge.settings','model.capabilities','task.runtime.templates','task.runtime.workflow.get','task.runtime.workflow.update','task.runtime.pause'])allowed.add(operation);
  if (!allowed.has(operation)) throw new Error("Unsupported task operation");
  if (["task.start","task.resume","task.continue"].includes(operation)) {
    if (runtimeUpdater?.isUpgrading()) throw new Error("OpenCode 正在升级");
    if (preparingOpenCodeTask || activeOpenCodeTurns.size) throw new Error("已有 OpenCode 任务执行中");
    if (!openCodeRuntime.resolveBinary()) throw new Error("未找到锁定的 OpenCode 运行时");
    const continuation = operation === "task.continue" ? String(payload.prompt ?? "").trim() : "";
    if (operation === "task.continue" && (!continuation || continuation.length > 4000)) throw new Error("追加任务须为 1–4000 字");
    preparingOpenCodeTask = true;
    try {
      const prepared = await sendRequest("task.external.prepare", "task.loaded", payload, {threadId}, 300_000);
      const task = prepared.payload?.task as OpenCodeTask;
      if (!task?.id || !path.isAbsolute(task.workspace)) throw new Error("Task 工作区准备失败");
      const priorFailures = task.verification?.filter(result => !result.ok).map(result => result.summary?.slice(0,750)).slice(0,4).join("\n");
      const prompt = [task.goal, continuation, priorFailures && "上次独立验收失败：\n"+priorFailures,
        "检查实际工作区并保留已完成的变更。修复源码，保留现有测试预期。"].filter(Boolean).join("\n\n");
      await startOpenCodeTurn(threadId, prompt, undefined, task);
      return prepared;
    } finally {
      preparingOpenCodeTask = false;
    }
  }
  const activeTask = [...activeOpenCodeTurns.entries()].find(([,turn]) => turn.taskId === payload.task_id && turn.threadId === threadId);
  if (operation === "task.append") {
    if (!activeTask) throw new Error("任务未在执行");
    const result = await appendOpenCodeTurn(threadId,activeTask[0],String(payload.prompt??""),String(payload.message_id??""));
    return {type:"task.loaded",payload:{followup:result.payload}};
  }
  if (activeTask && (operation === "task.pause" || operation === "task.cancel")) {
    const turn = activeTask[1];
    await stopOpenCodeTurn(turn, operation === "task.pause");
    return sendRequest("task.list", "task.loaded", {}, {threadId});
  }
  const result = await sendRequest(operation, operation.startsWith('knowledge.')?'knowledge.loaded':operation==='model.capabilities'?'model.capabilities.loaded':"task.loaded", payload, {threadId}, operation === "task.model.diagnostic" ? 300000 : operation === "task.connection.test" ? 30000 : 15000);
  return result;
});
ipcMain.handle("agent:plan-request", async (_event, threadId: string, operation: string, payload: Record<string, unknown> = {}) => {
  const allowed = new Set(["plan.list", "plan.create", "plan.step.update", "plan.step.edit", "plan.steps.reorder", "plan.checkpoint", "plan.resume", "plan.resume.confirm", "plan.recover", "plan.execution.extend", "plan.operation.review"]);
  if (!allowed.has(operation)) throw new Error("Unsupported plan operation");
  return sendRequest(operation, operation === "plan.resume" ? "plan.resumable" : "plan.loaded",
    { ...payload, thread_id: threadId }, { threadId }, operation==='plan.operation.review'?300000:25000);
});
ipcMain.handle("agent:thread-rename", async (_event, threadId: string, title: string, projectId?: string) => {
  return sendRequest("thread.rename", "thread.updated", { title, project_id:projectId }, { threadId });
});
ipcMain.handle("agent:thread-delete", async (_event, threadId:string, projectId:string) => {
  for (const [, entry] of activeOpenCodeTurns.entries()) {
    if (entry.threadId === threadId) {
      entry.cancelled = true;
      entry.outcome = "interrupted";
      entry.controller.abort();
      if (entry.sessionId) await openCodeRuntime.interrupt(entry.sessionId).catch(() => {});
    }
  }
  try {
    if (openCodeRuntime.status().running) {
      const binding = await openCodeRuntime.bindings().get(threadId).catch(() => undefined);
      if (binding?.sessionId) await openCodeRuntime.deleteSession(binding.sessionId).catch(() => {});
    }
  } catch {}
  return sendRequest("thread.delete", "thread.deleted", {project_id:projectId, cancel_tasks:true}, {threadId}, 60_000);
});
ipcMain.handle("agent:thread-get", async (_event, threadId: string) => {
  return sendRequest(
    "thread.get",
    "thread.loaded",
    { thread_id: threadId },
    { threadId }
  );
});
async function startOpenCodeTurn(threadId: string, prompt: string, model?: string, task?:OpenCodeTask): Promise<AgentEnvelope> {
  if (openCodeRuntime.bundledVersion()) installedRuntimeUpdater();
  if (runtimeUpdater?.isUpgrading()) throw new Error("OpenCode 正在升级");
  if (shuttingDown || quitInProgress) throw new Error("应用正在关闭");
  if (activeOpenCodeTurns.size || (preparingOpenCodeTask && !task)) throw new Error("已有 OpenCode 执行占用工作区，请等待或停止。");
  if (typeof prompt !== "string" || !prompt.trim() || Buffer.byteLength(prompt) > 48000) throw new Error("请输入有效任务内容");
  if (!openCodeRuntime.resolveBinary()) throw new Error("未找到锁定的 OpenCode 运行时，请检查安装完整性。");
  const turnId = "turn_" + randomUUID().replace(/-/g, "");
  const startedAt = new Date().toISOString();
  broadcastAgentEvent({ type: "turn.started", request_id: "req_" + randomUUID().replace(/-/g, ""), turn_id: turnId, thread_id: threadId, timestamp: startedAt, payload: { engine: "opencode" } });
  const entry: OpenCodeTurn = { controller: new AbortController(), cancelled: false, outcome: "failed", threadId, goal:task?.goal ?? prompt, done: Promise.resolve(), appended: new Set(), taskId:task?.id };
  activeOpenCodeTurns.set(turnId, entry);
  entry.done = (async () => {
    let assistant = "";
    let follow: Promise<void> | undefined;
    let terminal = false;
    let gateway: Awaited<ReturnType<typeof startOpenCodeModel>> | undefined;
    let releaseLease: (()=>Promise<void>) | undefined;
    let finalEvent: AgentEnvelope | undefined;
    const end = (type:string, message?:string) => {
      finalEvent = {type, request_id:"req_"+randomUUID().replace(/-/g,""), turn_id:turnId, thread_id:threadId,
        timestamp:new Date().toISOString(), payload:{engine:"opencode", ...(message ? {message} : {})}};
    };
    try {
      const threadRes = await sendRequest("thread.get", "thread.loaded", { thread_id: threadId }, { threadId });
      const projectId = threadRes.payload?.project_id;
      if (typeof projectId !== "string" || (threadRes.payload?.thread as {id?:string})?.id !== threadId) throw new Error("会话归属校验失败");
      entry.projectId = projectId;
      const [projectRes, catalogRes, permissionRes] = await Promise.all([
        sendRequest("project.get", "project.loaded", {project_id:projectId}, { threadId }),
        sendRequest("task.catalog.get", "task.loaded", {}, { threadId }),
        sendRequest("permission.get", "permission.loaded", {project_id:projectId}, { threadId }),
      ]);
      const registeredPath = (projectRes.payload?.project as {path?:string; id?:string})?.path;
      if (!registeredPath || !path.isAbsolute(registeredPath) || (projectRes.payload?.project as {id?:string})?.id !== projectId) throw new Error("工程目录无法确认");
      const projectPath = task?.workspace ?? registeredPath;
      const mode = permissionRes.payload?.mode as OpenCodePermissionMode;
      if (!["read_only", "workspace", "full_access"].includes(mode)) throw new Error("无法确认执行权限");
      const catalog = (catalogRes as any)?.payload?.catalog;
      const config = task?.config ?? (catalogRes as any)?.payload?.config ?? {};
      const credentials = {...readModelCredentials(), "legacy-openai":currentOpenAIKey() ?? ""};
      const taskProfile = task?.config.roles?.executor?.model_profile_id;
      const threadModel = (threadRes.payload?.thread as {active_model?:string})?.active_model;
      const selectedProfileId = selectOpenCodeProfile(catalog, taskProfile ? "profile:"+taskProfile : model ?? threadModel, catalogRes.payload?.chat_default, config);
      if (task?.opencode_local_only && !catalog.connections.some((connection:any) =>
        connection.provider_type === "ollama" && catalog.profiles.some((profile:any) =>
          profile.model_profile_id === selectedProfileId && profile.connection_id === connection.connection_id))) {
        throw new Error("当前 Task 仅允许 Ollama，请明确选择本地模型");
      }
      entry.controller.signal.throwIfAborted();
      releaseLease = await acquireEngineLease(process.env.LCA_DATA_DIR || app.getPath("userData"));
      gateway = await startOpenCodeModel(catalog, config, credentials, selectedProfileId,
        catalogRes.payload?.global_usage as {api_calls?:number; reserved_tokens?:number} | undefined,
        async (input_bytes, max_output) => {
          entry.controller.signal.throwIfAborted();
          await sendRequest("task.external.reserve", "task.loaded", {
            project_id:projectId, task_id:task?.id, turn_id:turnId, profile_id:selectedProfileId, input_bytes, max_output,
          }, {threadId});
        });
      await openCodeRuntime.ensureStarted(gateway.configContent, projectPath);
      entry.controller.signal.throwIfAborted();
      const bindingKey = task ? "task:" + task.id : threadId;
      const binding = await openCodeRuntime.bindings().get(bindingKey);
      if (binding && (binding.engine !== "opencode" || path.relative(binding.projectRoot, projectPath) !== "")) throw new Error("会话与当前工程不匹配");
      let sessionId = binding?.sessionId;
      let newSession = false;
      if (sessionId) {
        try {
          const snapshot = await openCodeRuntime.getSession(sessionId) as {data?:{id?:string;location?:{directory?:string}}};
          if (snapshot.data?.id !== sessionId || !snapshot.data.location?.directory ||
              path.relative(projectPath, snapshot.data.location.directory) !== "") throw new Error("运行时会话目录不匹配");
          await openCodeRuntime.updatePermissions(sessionId, mode);
        } catch (error) {
          if (!(error instanceof SidecarHttpError && error.status === 404)) throw error;
          sessionId = undefined;
        }
      }
      if (!sessionId) {
        sessionId = await openCodeRuntime.createSession(prompt.slice(0, 80), projectPath, bindingKey, mode);
        newSession = true;
      }
      entry.sessionId = sessionId;
      await openCodeRuntime.selectModel(sessionId, gateway.model);
      entry.controller.signal.throwIfAborted();
      await sendRequest("turn.record_external", "turn.recorded", { project_id:projectId, role: "user", content: prompt }, { threadId });
      let effectivePrompt = prompt;
      if (newSession && !task) {
        const msgs = Array.isArray((threadRes as any)?.payload?.messages) ? (threadRes as any).payload.messages : [];
        const recent = msgs.slice(-8).map((m: any) => `${String(m.role || "user")}: ${String(m.content || "").slice(0, 500)}`).join("\n");
        if (recent.trim()) {
          effectivePrompt = `Project: ${projectPath}\nRecent conversation context:\n${recent}\n\nCurrent user request:\n${prompt}`;
        } else {
          effectivePrompt = `Project: ${projectPath}\n\nUser request:\n${prompt}`;
        }
      }
      const bridge = openCodeRuntime.bridge(0);
      let streamReady!: () => void;
      const ready = new Promise<void>(resolve => { streamReady = resolve; });
      let finished = false;
      const toolCalls = new Map<string, { name: string; started: boolean }>();
      const startedAtMs = Date.now();
      let modelSteps = 0;
      let toolFailures = 0;
      const usageTotals = { input: 0, output: 0, total: 0 };
      const modelLabel = String(model?.startsWith("profile:") ? model.slice("profile:".length) : (model || (catalogRes as any)?.payload?.chat_default || "opencode"));
      const emitMetrics = () => {
        broadcastAgentEvent({ type: "turn.metrics", request_id: "req_" + randomUUID().replace(/-/g, ""), turn_id: turnId, thread_id: threadId, timestamp: new Date().toISOString(), payload: {
          provider: "opencode",
          model: modelLabel,
          execution_summary: {
            model_steps: modelSteps,
            tool_calls: toolCalls.size,
            tool_duration_ms: 0,
            tool_failures: toolFailures,
            provider_retries: 0,
            elapsed_ms: Math.max(0, Date.now() - startedAtMs),
            context_token_estimate: usageTotals.total || usageTotals.input,
            context_sources: { input_tokens: usageTotals.input, output_tokens: usageTotals.output, total_tokens: usageTotals.total },
          },
        } });
      };
      emitMetrics();
      let bridgeFailed = false;
      let terminalError = "";
      const appendDelta = (delta:string) => {
        if (!delta) return;
        assistant += delta;
        broadcastAgentEvent({ type: "turn.delta", request_id: "req_" + randomUUID().replace(/-/g, ""), turn_id: turnId, thread_id: threadId, timestamp: new Date().toISOString(), payload: { delta } });
      };
      follow = bridge.follow(sessionId, entry.controller.signal, (event) => {
        if (event.kind === "snapshot") {
          streamReady();
        } else if (event.kind === "text") {
          appendDelta(String((event.payload as any)?.delta ?? ""));
        } else if (event.kind === "usage") {
          const t = ((event.payload as any)?.tokens ?? event.payload ?? {}) as any;
          const inp = Number(t.input_tokens ?? t.input ?? t.prompt_tokens ?? 0) || 0;
          const out = Number(t.output_tokens ?? t.output ?? t.completion_tokens ?? 0) || 0;
          const total = Number(t.total_tokens ?? t.total ?? (inp + out)) || (inp + out);
          if (inp > 0) usageTotals.input = Math.max(usageTotals.input, inp);
          if (out > 0) usageTotals.output = Math.max(usageTotals.output, out);
          if (total > 0) usageTotals.total = Math.max(usageTotals.total, total);
          modelSteps += 1;
          emitMetrics();
        } else if (event.kind === "tool") {
          const p = (event.payload as any) || {};
          const type = String(p.type ?? "session.tool");
          const callId = String(p.callId ?? p.name ?? type);
          const name = String(p.name ?? (type.replace(/^session\.tool\./, "") || "tool"));
          const isEnd = type.endsWith(".completed") || type.endsWith(".failed") || type.endsWith(".error") || type.endsWith(".success");
          const isStart = type.endsWith(".started") || type.endsWith(".running") || type.endsWith(".called") || (!isEnd && !type.endsWith(".progress"));
          const existing = toolCalls.get(callId);
          if (isStart && !existing?.started) {
            toolCalls.set(callId, { name, started: true });
            broadcastAgentEvent({ type: "tool.requested", request_id: "req_" + randomUUID().replace(/-/g, ""), turn_id: turnId, thread_id: threadId, timestamp: new Date().toISOString(), payload: { tool_call_id: callId, name, arguments: p.input && typeof p.input === "object" ? p.input : {} } });
            broadcastAgentEvent({ type: "tool.started", request_id: "req_" + randomUUID().replace(/-/g, ""), turn_id: turnId, thread_id: threadId, timestamp: new Date().toISOString(), payload: { tool_call_id: callId } });
          }
          if (isEnd) {
            if (!existing?.started) {
              toolCalls.set(callId, { name, started: true });
              broadcastAgentEvent({ type: "tool.requested", request_id: "req_" + randomUUID().replace(/-/g, ""), turn_id: turnId, thread_id: threadId, timestamp: new Date().toISOString(), payload: { tool_call_id: callId, name, arguments: p.input && typeof p.input === "object" ? p.input : {} } });
            }
            const ok = !type.endsWith(".failed") && !type.endsWith(".error");
            if (!ok) toolFailures += 1;
            const out = p.output ?? p.error ?? {};
            broadcastAgentEvent({ type: "tool.completed", request_id: "req_" + randomUUID().replace(/-/g, ""), turn_id: turnId, thread_id: threadId, timestamp: new Date().toISOString(), payload: { tool_call_id: callId, result: { ok, summary: String((out as any)?.summary ?? (out as any)?.message ?? name), data: typeof out === "object" && out ? out : { output: out }, stdout: String((out as any)?.stdout ?? ""), stderr: String((out as any)?.stderr ?? ""), error: ok ? undefined : { code: "TOOL_FAILED", message: String((out as any)?.message ?? (out as any)?.error ?? type) } } } });
            emitMetrics();
          }
        } else if (event.kind === "approval") {
          const p = (event.payload as any) || {};
          const requestId = String(p.requestId ?? p.requestID ?? p.id ?? "");
          if (requestId) {
            const approvalId = "oc_" + requestId;
            const action = String(p.action ?? "permission");
            const resources:string[] = Array.isArray(p.resources) ? p.resources.filter((resource:unknown)=>typeof resource === "string") : [];
            const sensitive = resources.some(resource=>Object.values(credentials).some(key=>key.length>=12 && resource.includes(key)));
            if (["read","edit","grep","glob"].includes(action)) {
              const metadata = p.metadata && typeof p.metadata === "object" ? p.metadata : undefined;
              const targets = ["grep","glob"].includes(action) ? (metadata && metadata.hidden !== true ? [metadata.path ?? metadata.root] : []) : resources;
              const scoped = !sensitive && targets.length > 0 && targets.length <= 20 && targets.every(target=>isScopedResource(projectPath,target));
              if (!scoped || action !== "edit" || mode === "full_access") {
                void openCodeRuntime.replyPermission(sessionId,requestId,scoped ? "once" : "reject").catch(() => entry.controller.abort());
                return;
              }
            }
            pendingOpenCodeApprovals.set(approvalId, { sessionId, requestId, turnId, threadId, action, resources, sensitive });
            broadcastAgentEvent({ type: "approval.requested", request_id: "req_" + randomUUID().replace(/-/g, ""), turn_id: turnId, thread_id: threadId, timestamp: new Date().toISOString(), payload: {
              approval_id: approvalId,
              tool: action,
              arguments: sensitive ? {} : {resources:resources.slice(0,20).map(resource=>resource.slice(0,2000))},
              reason: sensitive ? "操作包含受保护凭据，系统将拒绝执行。" : "OpenCode 请求对此操作授予一次性权限。",
              risk: "sensitive",
              engine: "opencode",
            } });
          }
        } else if (event.kind === "diff") {
          const p = (event.payload as any) || {};
          const callId = "diff_" + randomUUID().slice(0, 8);
          broadcastAgentEvent({ type: "tool.requested", request_id: "req_" + randomUUID().replace(/-/g, ""), turn_id: turnId, thread_id: threadId, timestamp: new Date().toISOString(), payload: { tool_call_id: callId, name: "file_diff", arguments: {} } });
          broadcastAgentEvent({ type: "tool.started", request_id: "req_" + randomUUID().replace(/-/g, ""), turn_id: turnId, thread_id: threadId, timestamp: new Date().toISOString(), payload: { tool_call_id: callId } });
          broadcastAgentEvent({ type: "tool.completed", request_id: "req_" + randomUUID().replace(/-/g, ""), turn_id: turnId, thread_id: threadId, timestamp: new Date().toISOString(), payload: { tool_call_id: callId, result: { ok: true, summary: "???????", data: { diff: p.diff ?? p }, stdout: "", stderr: "" } } });
        } else if (event.kind === "execution-ended") {
          finished = true;
          terminal = true;
          const oc = String((event.payload as any)?.outcome ?? "failed");
          entry.outcome = oc;
          const error = (event.payload as {error?:unknown}).error;
          if (error && typeof error === "object") {
            const identity = (error as {name?:unknown; _tag?:unknown})._tag ?? (error as {name?:unknown}).name;
            if (typeof identity === "string" && /^[a-zA-Z0-9_.-]{1,100}$/.test(identity)) terminalError = identity;
          }
          entry.controller.abort();
        }
      }).catch(() => { bridgeFailed = true; });
      await Promise.race([ready, follow]);
      entry.controller.signal.throwIfAborted();
      if (bridgeFailed) throw new Error("OpenCode 事件流未连接");
      const messageId = "msg_"+turnId;
      await openCodeRuntime.prompt(sessionId, effectivePrompt,{id:messageId});
      const timeoutAt = Date.now() + gateway.durationMs;
      let nextReconcile = Date.now() + 3000;
      let reconnectDeadline = Infinity;
      let reconciledTerminal = false;
      const recover = () => openCodeRuntime.sessionContext(sessionId).then(context=>recoverCompletedExchange(context,messageId)).catch(()=>undefined);
      while (!finished && Date.now() < timeoutAt && !entry.controller.signal.aborted) {
        if (bridgeFailed && reconnectDeadline === Infinity) reconnectDeadline = Date.now() + 10000;
        if (Date.now() >= reconnectDeadline) break;
        if (Date.now() >= nextReconcile && timeoutAt - Date.now() > 1000) {
          nextReconcile = Date.now() + 5000;
          const snapshot = await openCodeRuntime.getSession(sessionId).catch(()=>undefined) as {data?:{id?:string;time?:{idle?:number;busy?:number}}}|undefined;
          const time = snapshot?.data?.time;
          if (!finished && !entry.controller.signal.aborted && snapshot?.data?.id === sessionId &&
              typeof time?.idle === "number" && typeof time.busy === "number" && time.idle >= Math.max(startedAtMs,time.busy)) {
            const recovered = await recover();
            if (recovered && !finished && !entry.controller.signal.aborted) {
              terminal = finished = true;
              reconciledTerminal = true;
              entry.outcome = recovered.outcome;
              if (recovered.text.startsWith(assistant)) appendDelta(recovered.text.slice(assistant.length));
              else {
                terminalError = "OPENCODE_RECOVERY_TEXT_MISMATCH";
                entry.outcome = "failed";
              }
              entry.controller.abort();
              break;
            }
          }
        }
        await new Promise((r) => setTimeout(r, 200));
      }
      entry.controller.abort();
      await follow.catch(() => {});
      if (!reconciledTerminal && terminal && entry.outcome === "succeeded" && !entry.cancelled) {
        const recovered = await recover();
        if (!entry.cancelled && recovered?.outcome === "succeeded" && recovered.text.startsWith(assistant)) {
          appendDelta(recovered.text.slice(assistant.length));
        }
      }
      if (assistant) await sendRequest("turn.record_external", "turn.recorded", { project_id:projectId, role: "assistant", content: assistant.slice(0,200000) }, { threadId });
      emitMetrics();
      if (entry.cancelled || entry.outcome === "interrupted") {
        end("turn.cancelled");
      } else if (!finished || entry.outcome !== "succeeded") {
        const usage = gateway.usage();
        const diagnostic = [terminalError, usage.lastStatus && `model relay HTTP ${usage.lastStatus}`, usage.failure, `requests=${usage.requests}`].filter(Boolean).join(" / ");
        const msg = Date.now() >= timeoutAt && !finished ? "OpenCode 执行超时" : bridgeFailed ? "OpenCode 连接中断或状态无法确认" : `OpenCode 执行失败 (${diagnostic})`;
        end("turn.failed",msg);
      } else {
        end("turn.completed");
      }
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      if (entry.cancelled) {
        end("turn.cancelled");
      } else {
        end("turn.failed",message);
      }
    } finally {
      entry.controller.abort();
      await follow;
      await gateway?.close().catch(() => {});
      if (entry.sessionId && (entry.cancelled || !terminal)) {
        await openCodeRuntime.interrupt(entry.sessionId).catch(() => {});
        await openCodeRuntime.stop().catch(() => {});
      }
      if (task) {
        try {
          const outcome = entry.cancelled ? (entry.pauseTask ? "paused" : "cancelled") :
            terminal && entry.outcome === "succeeded" ? "succeeded" : "failed";
          entry.verifying = outcome === "succeeded";
          const result = await sendRequest("task.external.finish", "task.loaded", {project_id:entry.projectId,task_id:task.id,outcome}, {threadId}, 600_000);
          broadcastAgentEvent({type:"task.updated",thread_id:threadId,turn_id:turnId,payload:result.payload});
          const state = result.payload?.task as {status?:string;reason?:string}|undefined;
          if (outcome === "succeeded" && state?.status !== "awaiting_approval") {
            end("turn.failed", state?.reason ?? "独立验收未通过");
          }
        } catch (error) {
          end("turn.failed",String(error));
        }
      }
      await releaseLease?.().catch(() => {});
      for (const [id, pending] of pendingOpenCodeApprovals) {
        if (pending.turnId === turnId) pendingOpenCodeApprovals.delete(id);
      }
      activeOpenCodeTurns.delete(turnId);
      if (entry.cancelled) end("turn.cancelled");
      if (finalEvent) broadcastAgentEvent(finalEvent);
    }
  })();
  void entry.done.catch(() => {});
  return { type: "turn.started", request_id: "req_" + randomUUID().replace(/-/g, ""), turn_id: turnId, thread_id: threadId, timestamp: startedAt, payload: { engine: "opencode" } };
}

ipcMain.handle("agent:turn-start", (_event, threadId: string, prompt: string, model?: string, _unified?: boolean, resume?:{run_id:string;confirm_workspace:boolean}) => {
  if (resume && resume.confirm_workspace !== true) throw new Error("请确认已检查当前工作区");
  return startOpenCodeTurn(threadId, prompt, model);
});
async function appendOpenCodeTurn(threadId: string, turnId: string, prompt: string, messageId: string) {
  const turn = activeOpenCodeTurns.get(turnId);
  if (!turn?.sessionId || turn.threadId !== threadId || turn.controller.signal.aborted) throw new Error("当前会话未在执行");
  if (!/^[a-zA-Z0-9_-]{1,128}$/.test(messageId)) throw new Error("无效追加消息 ID");
  if (!turn.appended.has(messageId)) {
    if (turn.appended.size >= 20) throw new Error("追加消息达到上限");
    turn.appended.add(messageId);
    await openCodeRuntime.prompt(turn.sessionId, prompt, {id:"msg_"+messageId,steer:true});
    await sendRequest("turn.record_external", "turn.recorded", { project_id:turn.projectId, role:"user", content:prompt }, {threadId});
  }
  return {type:"turn.appended", thread_id:threadId, turn_id:turnId, payload:{queued:true, message_id:messageId}};
}
ipcMain.handle("agent:turn-append", (_event, threadId: string, turnId: string, prompt: string, messageId: string) =>
  appendOpenCodeTurn(threadId,turnId,prompt,messageId));
async function stopOpenCodeTurn(turn:OpenCodeTurn, pause = false) {
  turn.pauseTask = pause;
  turn.cancelled = true;
  turn.controller.abort();
  if (turn.verifying && turn.taskId) {
    await sendRequest("task.external.stop", "task.loaded", {project_id:turn.projectId,task_id:turn.taskId,pause}, {threadId:turn.threadId});
  }
  await turn.done;
}
ipcMain.handle("agent:turn-cancel", async (_event, turnId: string) => {
  const oc = activeOpenCodeTurns.get(turnId);
  if (oc) {
    await stopOpenCodeTurn(oc);
    return { ok: true };
  }
  const socket = agentSocket;
  if (!socket || socket.readyState !== WebSocket.OPEN) {
    throw new Error("Agent WebSocket is not connected.");
  }
  const message: AgentEnvelope = {
    type: "turn.cancel",
    request_id: "req_" + randomUUID().replace(/-/g, ""),
    turn_id: turnId,
    timestamp: new Date().toISOString(),
    payload: {}
  };
  socket.send(JSON.stringify(message));
  return { ok: true };
});

app.whenReady().then(() => {
  appendRuntimeLog(
    "desktop.log",
    "Application ready version=" + app.getVersion() + " packaged=" + app.isPackaged
  );
  startAgent();
  createWindow();

  app.on("activate", () => {
    if (BrowserWindow.getAllWindows().length === 0) {
      createWindow();
    }
  });
});

app.on("before-quit", (event) => {
  updateManager?.cancel();
  if (quitReady) {
    return;
  }

  event.preventDefault();
  if (quitInProgress) {
    return;
  }

  quitInProgress = true;
  void (async ()=>{
    let timer:ReturnType<typeof setTimeout>|undefined;
    const drained = Promise.allSettled([...activeOpenCodeTurns.values()].map(turn=>stopOpenCodeTurn(turn,true)));
    try {
      await Promise.race([drained,new Promise<void>(resolve=>{timer=setTimeout(resolve,15000);})]);
    } finally {
      clearTimeout(timer);
    }
    await Promise.allSettled([openCodeRuntime.stop(),stopAgent()]);
  })().finally(()=>{quitReady=true;app.quit();});
});

app.on("window-all-closed", () => {
  if (process.platform !== "darwin") {
    app.quit();
  }
});
