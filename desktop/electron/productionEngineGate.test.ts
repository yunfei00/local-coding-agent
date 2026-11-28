import {describe,it,expect} from "vitest";
import {assertProductionEngine,legacyTaskPayload} from "./productionEngineGate";
describe("production engine admission",()=>{
 it("preserves legacy payloads",()=>{
  expect(legacyTaskPayload({prompt:"hello"})).toEqual({prompt:"hello"});
  expect(legacyTaskPayload({engine:"legacy",prompt:"hello"})).toEqual({prompt:"hello"});
 });
 it("rejects unavailable or malformed engine choices when gate closed",()=>{
  const prev = process.env.LCA_ENABLE_OPENCODE_PRODUCTION;
  process.env.LCA_ENABLE_OPENCODE_PRODUCTION = "0";
  for(const engine of ["opencode","unknown",null,{},true])expect(()=>assertProductionEngine(engine)).toThrow("gate closed");
  if (prev === undefined) delete process.env.LCA_ENABLE_OPENCODE_PRODUCTION;
  else process.env.LCA_ENABLE_OPENCODE_PRODUCTION = prev;
 });
 it("allows opencode when gate is open (default)",()=>{
  delete process.env.LCA_ENABLE_OPENCODE_PRODUCTION;
  expect(()=>assertProductionEngine("opencode")).not.toThrow();
 });
});
