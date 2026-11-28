import { WorkspaceEngineLock } from "./workspaceEngineLock";
// P1 contract. OpenCode execution stays fail-closed until P0/P3 gates pass.
export type EngineId = "legacy" | "opencode";
export type SessionBinding = { threadId: string; engine: EngineId; sessionId: string; projectRoot: string };
export interface AgentEngine {
  readonly id: EngineId;
  create(projectRoot: string, title: string): Promise<string>;
  status(sessionId: string): Promise<unknown>;
  // Resolves only after execution reaches a confirmed terminal state, not admission.
  send(sessionId: string, prompt: string): Promise<void>;
  cancel(sessionId: string): Promise<unknown>;
}
export class LegacyAdapter implements AgentEngine {
  readonly id = "legacy" as const;
  constructor(private readonly delegate: Omit<AgentEngine, "id">) {}
  create(root: string, title: string) { return this.delegate.create(root, title); }
  status(id: string) { return this.delegate.status(id); }
  send(id: string, prompt: string) { return this.delegate.send(id, prompt); }
  cancel(id: string) { return this.delegate.cancel(id); }
}
export class OpenCodeAdapter implements AgentEngine {
  readonly id = "opencode" as const;
  constructor(private readonly request: (route: string, method?: string, body?: unknown) => Promise<unknown>) {}
  async create(_root: string, title: string): Promise<string> {
    const result = await this.request("/api/session", "POST", { title, permissions: [{ action: "*", resource: "*", effect: "deny" }] }) as {data?: {id?: string}};
    if (!result?.data?.id) throw new Error("Missing OpenCode session ID");
    return result.data.id;
  }
  status(id: string) { return this.request("/api/session/" + encodeURIComponent(id)); }
  async send(id: string, prompt: string): Promise<void> {
    await this.request("/api/session/" + encodeURIComponent(id) + "/prompt", "POST", { text: prompt });
  }
  cancel(id: string) { return this.request("/api/session/" + encodeURIComponent(id) + "/interrupt", "POST"); }
}
export class EngineRouter {
  private readonly active = new Set<string>();
  private readonly workspaceLock = new WorkspaceEngineLock();
  constructor(private readonly legacy: AgentEngine, private readonly opencode: AgentEngine) {}
  engine(id: EngineId = "legacy"): AgentEngine {
    if (id === "legacy") return this.legacy;
    if (id === "opencode") return this.opencode;
    throw new Error("Unknown engine");
  }
  async run(binding: SessionBinding, prompt: string): Promise<void> {
    // OpenCode prompt admission does not hold the workspace lease until execution settles.
    if (binding.engine !== "legacy") throw new Error("OpenCode execution disabled");
    if (this.active.has(binding.threadId)) throw new Error("Thread already active");
    this.active.add(binding.threadId);
    try {
      const lease = await this.workspaceLock.acquire(binding.projectRoot, binding.engine, binding.threadId);
      try { await this.engine(binding.engine).send(binding.sessionId, prompt); }
      finally { lease.release(); }
    } finally { this.active.delete(binding.threadId); }
  }
}
