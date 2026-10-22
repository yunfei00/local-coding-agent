export type RoleProfile = {route: string; model: string; model_profile_id?: string; context_window: number | null; output_limit: number; tool_mode: string; input_price: number | null; output_price: number | null};
export type TaskConfig = {strategy: string; roles: Record<string, RoleProfile>; budget: Record<string, number | null>; verification_commands: string[]};
export type Connection = {connection_id: string; display_name: string; provider_type: "ollama" | "openai_compatible"; base_url: string; credential_reference: string | null; enabled: boolean};
export type ModelProfile = {model_profile_id: string; connection_id: string; model_id: string; display_name: string; context_window?: number | null; max_output_tokens?: number; temperature?: number | null; pricing?: {input_price?: number; output_price?: number} | null; tool_mode?: string};
export type ModelCatalog = {connections: Connection[]; profiles: ModelProfile[]};
export function modelLabel(catalog: ModelCatalog, model: ModelProfile): string {
  const connection = catalog.connections.find(c => c.connection_id === model.connection_id);
  return `${connection?.display_name ?? model.connection_id} / ${model.display_name} (${connection?.provider_type === "ollama" ? "Local" : "API"}) · ${model.model_profile_id}`;
}
