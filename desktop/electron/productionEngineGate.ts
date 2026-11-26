// Python owns the cross-process execution lease for legacy requests.
// Never acquire the same lease around admission-only WebSocket RPCs.
export function assertProductionEngine(engine:unknown= "legacy"):void{
 if(engine!=="legacy")throw new Error("Production OpenCode gate closed");
}
export function legacyTaskPayload(payload:Record<string,unknown>):Record<string,unknown>{
 assertProductionEngine(payload.engine);
 const {engine: _engine,...rest}=payload;
 return rest;
}
