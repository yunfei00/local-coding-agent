import { app } from "electron";
import { existsSync } from "node:fs";
import { createHash } from "node:crypto";
import path from "node:path";
import { EngineEventBridge, type EventSource } from "./engineEventBridge";
import { EngineSessionStore } from "./engineSessionStore";
import { buildOpenCodeConfig } from "./openCodeConfig";
import { OpenCodeSupervisor } from "./openCodeSupervisor";
import { productionPermissions, type OpenCodePermissionMode } from "./openCodePermissions";
import type {RuntimeVersion} from "./openCodeUpdateManager";

export type OpenCodeRuntimeStatus = {
  available: boolean;
  running: boolean;
  version: string;
  binary?: string;
  reason?: string;
};

const VERSION = "2.2.6";
const EXECUTABLE_SHA256 = "98cb0aa854c7c015cf6febafa7afb872c359bfe5a823a526f3b4fd347a9e9677";

export class OpenCodeRuntime implements EventSource {
  private readonly supervisor = new OpenCodeSupervisor();
  private store?: EngineSessionStore;
  private root?: string;
  private cwd?: string;
  private configHash?: string;
  private binaryPath?: string;
  private starting?: Promise<void>;
  private stopping?: Promise<void>;
  constructor(private readonly selectedVersion?: ()=>RuntimeVersion | undefined) {}

  binaryAvailable(): boolean {
    return !!this.resolveBinary();
  }

  status(): OpenCodeRuntimeStatus {
    const binary = this.resolveBinary();
    const running = this.supervisor.isRunning();
    return {
      available: !!binary,
      running,
      version: this.selectedVersion?.()?.version ?? VERSION,
      binary: this.binaryPath ?? binary,
      reason: !binary ? "OpenCode runtime not found" : undefined,
    };
  }

  resolveBinary(): string | undefined {
    const selected = this.selectedVersion?.();
    if (selected) return existsSync(selected.binary) ? selected.binary : undefined;
    return this.bundledVersion()?.binary;
  }

  bundledVersion(): RuntimeVersion | undefined {
    const candidates = app.isPackaged
      ? [path.join(process.resourcesPath, "opencode", "opencode.exe")]
      : [
          process.env.LCA_OPENCODE_BINARY?.trim(),
          path.resolve(app.getAppPath(), "../build/opencode-runtime/opencode.exe"),
        ].filter((value): value is string => Boolean(value));
    for (const candidate of candidates) {
      if (existsSync(candidate)) return {version:"v"+VERSION,binary:candidate,sha256:EXECUTABLE_SHA256};
    }
    return undefined;
  }

  async ensureStarted(configContent: string, cwd: string): Promise<void> {
    if (!path.isAbsolute(cwd)) throw new Error("OpenCode requires an explicit project directory");
    const wantedCwd = path.resolve(cwd);
    const hash = createHash("sha256").update(configContent).digest("hex");
    if (this.starting) await this.starting;
    if (this.stopping) await this.stopping;
    if (this.supervisor.isRunning() && this.cwd === wantedCwd && this.configHash === hash) return;
    if (this.root) await this.stop();
    this.starting = this.start(configContent, wantedCwd, hash).finally(() => { this.starting = undefined; });
    return this.starting;
  }

  private async start(configContent: string, cwd: string, hash: string): Promise<void> {
    const binary = this.resolveBinary();
    if (!binary) throw new Error("OpenCode runtime not found. Install bundled runtime or set LCA_OPENCODE_BINARY.");
    const project = createHash("sha256").update(process.platform === "win32" ? cwd.toLowerCase() : cwd).digest("hex");
    const selected = this.selectedVersion?.() ?? this.bundledVersion()!;
    const number = selected.version.replace(/^v/,"");
    // Keep the bundled data untouched while an independently managed version is active.
    const namespace = number === VERSION ? "opencode-projects" : "opencode-projects-"+selected.version;
    const root = path.join(app.getPath("userData"), namespace, project);
    this.binaryPath = binary;
    await this.supervisor.start(binary, root, {
      configContent,
      allowPrompt: true,
      expectedVersion: [number,"v"+number,"opencode v"+number],
      binarySha256: selected.sha256,
      cwd,
    });
    this.root = root;
    this.cwd = cwd;
    this.configHash = hash;
    const bindingFile = number === VERSION ? "opencode-session-bindings.json" : namespace+"-session-bindings.json";
    this.store = new EngineSessionStore(path.join(app.getPath("userData"), bindingFile));
  }

  async stop(): Promise<void> {
    if (this.stopping) return this.stopping;
    if (this.starting) await this.starting.catch(() => {});
    this.stopping = (async () => {
      try { await this.supervisor.stop(); }
      finally { this.root = undefined; this.cwd = undefined; this.configHash = undefined; this.store = undefined; this.stopping = undefined; }
    })();
    return this.stopping;
  }

  bindings(): EngineSessionStore {
    if (!this.store) throw new Error("OpenCode runtime not started");
    return this.store;
  }

  async request(route: string, method = "GET", body?: unknown): Promise<unknown> {
    return this.supervisor.request(route, method, body);
  }

  async events(signal: AbortSignal): Promise<Response> {
    return this.supervisor.events(signal);
  }

  async createSession(title: string, projectRoot: string, threadId: string, mode: OpenCodePermissionMode): Promise<string> {
    const result = await this.request("/api/session", "POST", {
      title, location:{directory:projectRoot}, permissions:productionPermissions(mode),
    }) as { data?: { id?: string; location?:{directory?:string} } };
    const id = result?.data?.id;
    if (!id) throw new Error("Missing OpenCode session ID");
    if (!result.data?.location?.directory || path.relative(projectRoot,result.data.location.directory) !== "") {
      throw new Error("OpenCode created session outside the registered workspace");
    }
    const binding = { threadId, engine: "opencode" as const, sessionId: id, projectRoot };
    const existing = await this.bindings().get(threadId).catch(() => undefined);
    if (existing) await this.bindings().rebind(binding);
    else await this.bindings().bind(binding);
    return id;
  }

  async getSession(sessionId: string): Promise<unknown> {
    return this.request("/api/session/" + encodeURIComponent(sessionId));
  }

  async updatePermissions(sessionId: string, mode: OpenCodePermissionMode): Promise<void> {
    await this.request("/api/session/" + encodeURIComponent(sessionId), "PATCH", { permissions: productionPermissions(mode) });
  }

  async selectModel(sessionId: string, model: {id:string;providerID:string}): Promise<void> {
    await this.request("/api/session/" + encodeURIComponent(sessionId) + "/model", "POST", {model});
  }

  async prompt(sessionId: string, text: string, followupId?:string): Promise<void> {
    await this.request("/api/session/" + encodeURIComponent(sessionId) + "/prompt", "POST", {
      text, ...(followupId ? {delivery:"steer",id:"msg_"+followupId,resume:false} : {}),
    });
  }

  async interrupt(sessionId: string): Promise<unknown> {
    return this.request("/api/session/" + encodeURIComponent(sessionId) + "/interrupt", "POST");
  }

  async replyPermission(sessionId: string, requestId: string, reply: "once" | "always" | "reject"): Promise<unknown> {
    return this.request("/api/session/" + encodeURIComponent(sessionId) + "/permission/" + encodeURIComponent(requestId) + "/reply", "POST", { decision: reply });
  }

  async deleteSession(sessionId: string): Promise<void> {
    await this.request("/api/session/" + encodeURIComponent(sessionId), "DELETE");
  }

  bridge(retries = 3): EngineEventBridge {
    return new EngineEventBridge(this, retries);
  }
}

export function buildConfigFromCatalog(catalog: unknown, config: unknown, credentials: Record<string, string>, selectedProfileId?: string | null): string {
  return JSON.stringify(buildOpenCodeConfig({
    catalog: catalog as any,
    config: config as any,
    credentials,
    selectedProfileId,
  }));
}
