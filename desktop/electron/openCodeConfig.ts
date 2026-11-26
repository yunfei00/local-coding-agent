type Connection = { connection_id: string; display_name: string; provider_type: "ollama" | "openai_compatible"; base_url: string; credential_reference: string | null; enabled: boolean };
type ModelProfile = { model_profile_id: string; connection_id: string; model_id: string; display_name: string; context_window?: number | null; max_output_tokens?: number | null; temperature?: number | null; tool_mode?: string; supports_vision?: boolean };
type ModelCatalog = { connections: Connection[]; profiles: ModelProfile[] };
type TaskConfig = { roles?: Record<string, { model_profile_id?: string | null }> };

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

  for (const profile of catalog.profiles) {
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
  if (connection.provider_type === "ollama") return base;
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
