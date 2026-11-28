// v2.0.0 RC2: OpenCode is the sole formal execution engine.
// The production gate switch has been removed; OpenCode is always enabled.
export function openCodeProductionEnabled(): boolean {
  return true;
}

export function assertProductionEngine(engine: unknown): void {
  const value = engine === undefined ? "legacy" : engine;
  if (value === "legacy") return;
  if (value === "opencode") return;
  throw new Error("Production OpenCode gate closed");
}

export function legacyTaskPayload(payload: Record<string, unknown>): Record<string, unknown> {
  assertProductionEngine(payload.engine);
  const { engine: _engine, ...rest } = payload;
  return rest;
}