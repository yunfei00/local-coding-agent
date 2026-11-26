import {describe,it,expect} from "vitest";
import {assertProductionEngine,legacyTaskPayload} from "./productionEngineGate";
describe("production engine admission",()=>{
 it("preserves legacy payloads",()=>{
  expect(legacyTaskPayload({prompt:"hello"})).toEqual({prompt:"hello"});
  expect(legacyTaskPayload({engine:"legacy",prompt:"hello"})).toEqual({prompt:"hello"});
 });
 it("rejects unavailable or malformed engine choices",()=>{
  for(const engine of ["opencode","unknown",null,{},true])expect(()=>assertProductionEngine(engine)).toThrow("gate closed");
 });
});
