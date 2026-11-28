type Connection = { connection_id: string; display_name: string; provider_type: "ollama" | "openai_compatible"; base_url: string; credential_reference: string | null; enabled: boolean };
type ModelProfile = { model_profile_id: string; connection_id: string; model_id: string; display_name: string; context_window?: number | null; max_output_tokens?: number | null; temperature?: number | null; tool_mode?: string; supports_vision?: boolean };
type ModelCatalog = { connections: Connection[]; profiles: ModelProfile[] };
type TaskConfig = { roles?: Record<string, { model_profile_id?: string | null }>; budget?: Record<string, number | null> };

export type OpenCodeProviderConfig = {
  package: string;
  settings: { baseURL: string; apiKey?: string };
  models: Record<string, { name: string; capabilities?: { tools?: boolean }; limit?: { context?: number; output?: number } }>;
};

export type OpenCodeConfig = {
  providers?: Record<string, OpenCodeProviderConfig>;
  provider?: Record<string, never>;
  enabled_providers?: string[];
  policies?: Array<{ action: string; resource: string; effect: string }>;
  model?: string;
};

export function buildOpenCodeConfig(options: {
  catalog: ModelCatalog;
  config: TaskConfig;
  credentials: Record<string, string>;
  selectedProfileId?: string | null;
}): OpenCodeConfig {
  const { catalog, config, credentials, selectedProfileId } = options;
  const enabledConnections = new Map(
    catalog.connections.filter((c) => c.enabled).map((c) => [c.connection_id, c]),
  );
  const providers: Record<string, OpenCodeProviderConfig> = {};
  const selectedProfile = selectedProfileId ? catalog.profiles.find(profile =>
    profile.model_profile_id === selectedProfileId && enabledConnections.has(profile.connection_id)) : undefined;
  if (selectedProfileId && !selectedProfile) throw new Error("Selected OpenCode profile is unavailable");

  for (const profile of catalog.profiles) {
    if (selectedProfile && profile !== selectedProfile) continue;
    const connection = enabledConnections.get(profile.connection_id);
    if (!connection) continue;
    const providerId = sanitizeId(connection.connection_id);
    const provider = providers[providerId] ?? {
      package: "@opencode/ai/providers/openai-compatible",
      settings: { baseURL: normalizeBaseUrl(connection) },
      models: {},
    };
    const credential = resolveCredential(connection, credentials);
    if (credential) provider.settings.apiKey = credential;
    else if (connection.provider_type === "ollama") provider.settings.apiKey = "ollama";
    provider.models[sanitizeModelKey(profile.model_id)] = {
      name: profile.display_name || profile.model_id,
      capabilities: { tools: profile.tool_mode !== "none" },
      limit: {
        ...(typeof profile.context_window === "number" ? { context: profile.context_window } : {}),
        ...(typeof profile.max_output_tokens === "number" ? { output: profile.max_output_tokens } : {}),
      },
    };
    providers[providerId] = provider;
  }

  const profileIds = new Set(catalog.profiles.map((p) => p.model_profile_id));
  const selected = selectedProfileId && profileIds.has(selectedProfileId) ? selectedProfileId : null;
  const executor = config.roles?.executor?.model_profile_id;
  const defaultProfileId = selected || (executor && profileIds.has(executor) ? executor : null);
  const model = defaultProfileId ? resolveModelRef(defaultProfileId, catalog, enabledConnections) : undefined;

  const providerIds = Object.keys(providers);
  const policies = [
    { action: "provider.use", resource: "*", effect: "deny" as const },
    ...providerIds.map((id) => ({ action: "provider.use", resource: id, effect: "allow" as const })),
  ];

  return {
    providers,
    policies,
    ...(model ? { model } : {}),
  };
}

function sanitizeId(value: string): string {
  return value.replace(/[^A-Za-z0-9_-]/g, "-").replace(/^-+|-+$/g, "").slice(0, 100) || "provider";
}

function sanitizeModelKey(modelId: string): string {
  return modelId.trim();
}

function normalizeBaseUrl(connection: Connection): string {
  const base = connection.base_url.replace(/\/+$/, "");
  return base.endsWith("/v1") ? base : `${base}/v1`;
}

function resolveCredential(connection: Connection, credentials: Record<string, string>): string | undefined {
  const ref = connection.credential_reference;
  if (ref && typeof credentials[ref] === "string" && credentials[ref]) return credentials[ref];
  const byConnection = credentials[`connection-${connection.connection_id}`];
  if (typeof byConnection === "string" && byConnection) return byConnection;
  if (ref === "legacy-openai" && typeof credentials["legacy-openai"] === "string" && credentials["legacy-openai"]) {
    return credentials["legacy-openai"];
  }
  return undefined;
}

function resolveModelRef(
  profileId: string,
  catalog: ModelCatalog,
  enabledConnections: Map<string, Connection>,
): string | undefined {
  const profile = catalog.profiles.find((p) => p.model_profile_id === profileId);
  if (!profile) return undefined;
  const connection = enabledConnections.get(profile.connection_id);
  if (!connection) return undefined;
  return `${sanitizeId(connection.connection_id)}/${sanitizeModelKey(profile.model_id)}`;
}

export function buildDiagnosticOpenCodeConfig(): OpenCodeConfig {
  return {
    provider: {},
    enabled_providers: [],
    policies: [{ action: "provider.use", resource: "*", effect: "deny" }],
  };
}
import { startCompatibleGateway } from "./localModelGateway";


export function selectOpenCodeProfile(catalog: ModelCatalog, selection: string | undefined, saved: unknown, config: TaskConfig): string {
  const candidates = catalog.profiles.filter(profile =>
    catalog.connections.some(connection => connection.enabled && connection.connection_id === profile.connection_id));
  if (selection?.startsWith("profile:")) {
    const id = selection.slice("profile:".length);
    if (candidates.some(profile => profile.model_profile_id === id)) return id;
  } else if (selection && selection !== "auto") {
    const matching = candidates.filter(profile => profile.model_id === selection);
    if (matching.length === 1) return matching[0].model_profile_id;
  } else {
    const id = saved || config.roles?.executor?.model_profile_id;
    if (typeof id === "string" && candidates.some(profile => profile.model_profile_id === id)) return id;
    if (!id && candidates.length === 1) return candidates[0].model_profile_id;
  }
  throw new Error("请选择 Settings 中明确可用的模型");
}

export async function startOpenCodeModel(catalog: ModelCatalog, config: TaskConfig, credentials: Record<string, string>,
  profileId: string, globalUsage: {api_calls?:number; reserved_tokens?:number} = {}) {
  const spec = buildOpenCodeConfig({catalog, config, credentials, selectedProfileId:profileId});
  const profile = catalog.profiles.find(item => item.model_profile_id === profileId)!;
  const connection = catalog.connections.find(item => item.connection_id === profile.connection_id)!;
  const providerID = sanitizeId(connection.connection_id);
  const provider = spec.providers![providerID];
  const limits = provider.models[profile.model_id].limit ?? {};
  const maxOutput = limits.output ?? 2048;
  const budget = config.budget ?? {};
  const online = connection.provider_type === "openai_compatible";
  if (online && (budget.api_cost != null || budget.global_api_cost != null)) {
    throw new Error("OpenCode 暂不能验证金额预算，已停止在线请求");
  }
  const requests = online ? Math.min(budget.api_calls ?? 0, (budget.global_api_calls ?? 0) - (globalUsage.api_calls ?? 0), 32) : 32;
  const reserveTokens = online ? Math.min(budget.api_tokens ?? 0, (budget.global_api_tokens ?? 0) - (globalUsage.reserved_tokens ?? 0)) : 2_000_000;
  if (requests < 1 || reserveTokens <= maxOutput) throw new Error("BUDGET_EXHAUSTED：执行预算耗尽");
  const durationMs = Math.min((budget.task_seconds ?? 600) * 1000, 600_000);
  const gateway = await startCompatibleGateway(profile.model_id, {baseUrl:provider.settings.baseURL, apiKey:provider.settings.apiKey}, {
    requests, reserveTokens, inputBytes:Math.min(2_000_000,reserveTokens), maxOutput, durationMs,
    requestMs:Math.min((budget.request_seconds ?? 120) * 1000,durationMs),
    temperature: profile.temperature ?? undefined, allowTools: profile.tool_mode !== "none",
    reasoningEffort: connection.provider_type === "ollama" && profile.model_id === "qwen3:4b" ? "none" : undefined,
  });
  provider.settings = {baseURL:`http://127.0.0.1:${gateway.port}/v1`,apiKey:gateway.token};
  return {configContent:JSON.stringify(spec), model:{providerID,id:profile.model_id}, durationMs, close:gateway.close, usage:gateway.usage, online};
}
