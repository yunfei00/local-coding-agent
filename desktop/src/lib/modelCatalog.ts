export type RoleProfile = {route: string; model: string; model_profile_id?: string; context_window: number | null; output_limit: number; tool_mode: string; input_price: number | null; output_price: number | null};
export type TaskConfig = {strategy: string; roles: Record<string, RoleProfile>; budget: Record<string, number | null>; verification_commands: string[]; gui_verification?: Record<string, unknown> | null; vision_profile_id?:string|null};
export type Connection = {connection_id: string; display_name: string; provider_type: "ollama" | "openai_compatible"; base_url: string; credential_reference: string | null; enabled: boolean};
export type ModelProfile = {model_profile_id: string; connection_id: string; model_id: string; display_name: string; context_window?: number | null; max_output_tokens?: number; temperature?: number | null; pricing?: {input_price?: number; output_price?: number} | null; tool_mode?: string; supports_vision?: boolean};
export type ModelCatalog = {connections: Connection[]; profiles: ModelProfile[]};
// Explicit opt-in for saved small budgets; keep cost caps, retries and model bindings.
export function longTaskBudget(config: TaskConfig): TaskConfig {
  const floors: Record<string, number> = {api_calls:200, api_tokens:10000000,
    global_api_calls:2000, global_api_tokens:100000000, task_seconds:7200};
  return {...config, budget:{...config.budget, ...Object.fromEntries(
    Object.entries(floors).map(([key, value]) => [key, Math.max(config.budget[key] ?? 0, value)]))}};
}
// Send deliberate field edits only. Unchanged cached defaults must never shadow
// Settings saved while the Task panel was open (including role bindings/zeros).
export function taskConfigOverrides(saved: TaskConfig, edited: TaskConfig): Record<string, unknown> {
  const changes: Record<string, unknown> = {};
  if (saved.strategy !== edited.strategy) changes.strategy = edited.strategy;
  if (saved.vision_profile_id !== edited.vision_profile_id) changes.vision_profile_id = edited.vision_profile_id;
  if (JSON.stringify(saved.gui_verification) !== JSON.stringify(edited.gui_verification)) changes.gui_verification = edited.gui_verification;
  if (JSON.stringify(saved.verification_commands) !== JSON.stringify(edited.verification_commands)) changes.verification_commands = edited.verification_commands;
  const budget = Object.fromEntries(Object.entries(edited.budget).filter(([key,value]) => saved.budget[key] !== value));
  if (Object.keys(budget).length) changes.budget = budget;
  const roles: Record<string, unknown> = {};
  for (const [role, profile] of Object.entries(edited.roles)) {
    const patch = Object.fromEntries(Object.entries(profile).filter(([key,value]) => saved.roles[role]?.[key as keyof RoleProfile] !== value));
    if (Object.keys(patch).length) roles[role] = patch;
  }
  if (Object.keys(roles).length) changes.roles = roles;
  return changes;
}
export function modelLabel(catalog: ModelCatalog, model: ModelProfile): string {
  const connection = catalog.connections.find(c => c.connection_id === model.connection_id);
  return `${connection?.display_name ?? model.connection_id} / ${model.display_name} (${connection?.provider_type === "ollama" ? "Local" : "API"}) · ${model.model_profile_id}`;
}
