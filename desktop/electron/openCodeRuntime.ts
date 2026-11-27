import { app } from "electron";
import { existsSync } from "node:fs";
import { mkdtemp, readFile } from "node:fs/promises";
import path from "node:path";
import os from "node:os";
import { EngineEventBridge, type EventSource } from "./engineEventBridge";
import { EngineSessionStore } from "./engineSessionStore";
import { buildOpenCodeConfig } from "./openCodeConfig";
import { OpenCodeSupervisor } from "./openCodeSupervisor";
import { acquireEngineLease } from "./engineLease";
import { openCodeProductionEnabled } from "./productionEngineGate";

export type OpenCodeRuntimeStatus = {
  available: boolean;
  running: boolean;
  version: string;
  binary?: string;
  reason?: string;
};

const VERSION = "2.2.6";
const VERSION_ALIASES = ["2.2.6", "v2.2.6", "opencode v2.2.6"];
const EXECUTABLE_SHA256 = "98cb0aa854c7c015cf6febafa7afb872c359bfe5a823a526f3b4fd347a9e9677";
const ACTIVATION_BLOCK = "OpenCode production execution disabled: security and budget gates pending";

export class OpenCodeRuntime implements EventSource {
  private readonly supervisor = new OpenCodeSupervisor();
  private store?: EngineSessionStore;
  private root?: string;
  private cwd?: string;
  private binaryPath?: string;
  private starting?: Promise<void>;
  private stopping?: Promise<void>;

  binaryAvailable(): boolean {
    return !!this.resolveBinary();
  }

  status(): OpenCodeRuntimeStatus {
    const binary = this.resolveBinary();
    const gated = !openCodeProductionEnabled();
    const running = this.supervisor.isRunning();
    return {
      available: !!binary && !gated,
      running,
      version: VERSION,
      binary: this.binaryPath ?? binary,
      reason: !binary ? "OpenCode runtime not found" : gated ? ACTIVATION_BLOCK : undefined,
    };
  }

  resolveBinary(): string | undefined {
    const env = process.env.LCA_OPENCODE_BINARY?.trim();
    const candidates = [
      env,
      path.join(process.resourcesPath || "", "opencode", "opencode.exe"),
      path.join(app.getAppPath(), "..", "opencode", "opencode.exe"),
      path.join(process.cwd(), "build", "opencode-p1", "verified-bin", "opencode.exe"),
      path.join(process.cwd(), "build", "opencode-p0", "verified-bin", "opencode.exe"),
    ].filter((v): v is string => !!v);
    for (const candidate of candidates) {
      if (existsSync(candidate)) return candidate;
    }
    return undefined;
  }

  async ensureStarted(configContent: string, cwd?: string): Promise<void> {
    if (!this.status().available) throw new Error(ACTIVATION_BLOCK);
    const wantedCwd = cwd ? path.resolve(cwd) : process.cwd();
    if (this.root && !this.supervisor.isRunning()) {
      this.root = undefined; this.cwd = undefined; this.store = undefined;
    }
    if (this.root && this.cwd === wantedCwd) return;
    if (this.root && this.cwd !== wantedCwd) await this.stop();
    if (this.starting) return this.starting;
    this.starting = this.start(configContent, wantedCwd).finally(() => { this.starting = undefined; });
    return this.starting;
  }

  private async start(configContent: string, cwd: string): Promise<void> {
    const binary = this.resolveBinary();
    if (!binary) throw new Error("OpenCode runtime not found. Install bundled runtime or set LCA_OPENCODE_BINARY.");
    const root = await mkdtemp(path.join(app.getPath("userData"), "opencode-runtime-"));
    this.binaryPath = binary;
    await this.supervisor.start(binary, root, {
      configContent,
      allowPrompt: true,
      expectedVersion: VERSION_ALIASES,
      binarySha256: EXECUTABLE_SHA256,
      cwd,
    });
    this.root = root;
    this.cwd = cwd;
    this.store = new EngineSessionStore(path.join(app.getPath("userData"), "opencode-session-bindings.json"));
  }

  async restart(configContent: string): Promise<void> {
    await this.stop();
    await this.ensureStarted(configContent);
  }

  async stop(): Promise<void> {
    if (this.stopping) return this.stopping;
    this.stopping = (async () => {
      try { await this.supervisor.stop(); }
      finally { this.root = undefined; this.cwd = undefined; this.store = undefined; this.stopping = undefined; }
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

  async createSession(title: string, projectRoot: string, threadId: string): Promise<string> {
    const result = await this.request("/api/session", "POST", { title, permissions: [{ action: "*", resource: "*", effect: "allow" }] }) as { data?: { id?: string } };
    const id = result?.data?.id;
    if (!id) throw new Error("Missing OpenCode session ID");
    const binding = { threadId, engine: "opencode" as const, sessionId: id, projectRoot };
    const existing = await this.bindings().get(threadId).catch(() => undefined);
    if (existing) await this.bindings().rebind(binding);
    else await this.bindings().bind(binding);
    return id;
  }

  async getSession(sessionId: string): Promise<unknown> {
    return this.request("/api/session/" + encodeURIComponent(sessionId));
  }

  async prompt(sessionId: string, text: string): Promise<void> {
    await this.request("/api/session/" + encodeURIComponent(sessionId) + "/prompt", "POST", { text });
  }

  async interrupt(sessionId: string): Promise<unknown> {
    return this.request("/api/session/" + encodeURIComponent(sessionId) + "/interrupt", "POST");
  }

  async replyPermission(sessionId: string, requestId: string, reply: "once" | "always" | "reject"): Promise<unknown> {
    return this.request("/api/session/" + encodeURIComponent(sessionId) + "/permission/" + encodeURIComponent(requestId) + "/reply", "POST", { reply });
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
