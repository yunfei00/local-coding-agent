// Python owns the cross-process execution lease for legacy requests.
// Never acquire the same lease around admission-only WebSocket RPCs.
const OPENCODE_PRODUCTION_ENV = "LCA_ENABLE_OPENCODE_PRODUCTION";

export function openCodeProductionEnabled(): boolean {
  return process.env[OPENCODE_PRODUCTION_ENV] === "1";
}

export function assertProductionEngine(engine:unknown):void{
  const value = engine === undefined ? "legacy" : engine;
  if (value === "legacy") return;
  if (value === "opencode" && openCodeProductionEnabled()) return;
  throw new Error("Production OpenCode gate closed");
}
export function legacyTaskPayload(payload:Record<string,unknown>):Record<string,unknown>{
 assertProductionEngine(payload.engine);
 const {engine: _engine,...rest}=payload;
 return rest;
}
