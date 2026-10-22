export type TaskSnapshot = {
  id: string; thread_id: string; revision: number; goal: string; status: string; reason: string;
  workspace: string; branch: string; attempts: number; repairs: number; escalations: number; elapsed_seconds: number;
  usage: {api_calls: number; local_calls: number; reserved_tokens: number; input_tokens: number; output_tokens: number;
    cached_tokens: number; reserved_cost: number; actual_cost: number; actual_cost_known: boolean; estimated: boolean; precision: string};
  plan: {steps: Array<{id: string; description: string; state: string}>};
  verification: Array<{command: string; ok: boolean; category: string; exit_code: number | null; duration_ms: number; summary: string; log_path?: string}>;
  report: {review?: string; diff?: string; git_approval?: string};
  config?: {budget: Record<string, number | null>};
  planning_attempts?: number; last_error?: {code:string; budget?: {scope:string; field:string; limit:number; used:number; required:number; remaining:number; input_token_estimate:number; output_limit:number; request_token_reservation:number; api_calls:number; reserved_tokens:number; rule:string}};
  calls?: Array<{id:string; created_at:number; role:string; model:string; route:string; status:string; usage:{provider?:string; connection_id?:string; model_profile_id?:string; phase?:string; sequence?:number; error_code?:string; http_status?:number; schema_valid?:boolean; next_state?:string}}>;
};

export function mergeTaskSnapshot(current: TaskSnapshot[], next: TaskSnapshot, threadId: string): TaskSnapshot[] {
  if (next.thread_id !== threadId) return current;
  const existing = current.find(task => task.id === next.id);
  if (existing && existing.revision > next.revision) return current;
  return [next, ...current.filter(task => task.id !== next.id)];
}

export function taskIsActive(task: Pick<TaskSnapshot, "status">): boolean {
  return ["pending", "planning", "executing", "verifying", "repairing", "escalating"].includes(task.status);
}
