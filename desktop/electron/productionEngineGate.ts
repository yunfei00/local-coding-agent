// Python owns the cross-process execution lease for legacy requests.
// Never acquire the same lease around admission-only WebSocket RPCs.
const OPENCODE_PRODUCTION_ENV = "LCA_ENABLE_OPENCODE_PRODUCTION";

export function openCodeProductionEnabled(): boolean {
  // v2.0.0 RC1: OpenCode is the default formal execution engine.
  // Gate is ON by default; can be explicitly disabled via env or settings.
  if (process.env[OPENCODE_PRODUCTION_ENV] === "0") return false;
  return process.env[OPENCODE_PRODUCTION_ENV] !== undefined
    ? process.env[OPENCODE_PRODUCTION_ENV] === "1"
    : true;
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
