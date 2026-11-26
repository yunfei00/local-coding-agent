import {describe,it,expect} from "vitest";
import {appendToolEvent} from "./ToolExecutionCards";
describe("tool cards",()=>{
 it("correlates explicit call IDs and preserves terminal status",()=>{
  const first=appendToolEvent([],{type:"session.tool.start",callId:"a",name:"read"});
  const done=appendToolEvent(first,{type:"session.tool.success",callId:"a"});
  expect(done).toHaveLength(1);expect(done[0].state).toBe("succeeded");expect(done[0].name).toBe("read");
  expect(appendToolEvent(done,{type:"session.tool.start",callId:"a"})[0].state).toBe("succeeded");
 });
 it("does not infer correlation without an ID",()=>{
  const first=appendToolEvent([],{type:"session.tool.start"});
  expect(appendToolEvent(first,{type:"session.tool.success"})).toHaveLength(2);
 });
 it("bounds history",()=>{
  let cards:ReturnType<typeof appendToolEvent>=[];
  for(let i=0;i<120;i++)cards=appendToolEvent(cards,{type:"session.tool.start",callId:String(i)});
  expect(cards).toHaveLength(100);
 });
});
