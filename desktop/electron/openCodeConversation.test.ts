import {describe,it,expect,vi} from "vitest";
import {OpenCodeConversation} from "./openCodeConversation";
describe("OpenCode conversation",()=>{
 const signal=new AbortController().signal;
 it("supports sequential turns and enforces the cumulative turn limit",async()=>{
  const execute=vi.fn(async()=>({outcome:"succeeded" as const,verified:false as const}));
  const conversation=new OpenCodeConversation({request:async()=>({data:{}})},"session",execute,3);
  for(const prompt of ["one","two","three"])await conversation.send(prompt,signal);
  expect(conversation.turns).toBe(3);
  await expect(conversation.send("four",signal)).rejects.toThrow("unavailable");
  expect(execute).toHaveBeenCalledTimes(3);
 });
 it("closes after uncertain execution without replay",async()=>{
  const execute=vi.fn(async()=>{throw new Error("unknown outcome");});
  const conversation=new OpenCodeConversation({request:async()=>({data:{}})},"session",execute);
  await expect(conversation.send("one",signal)).rejects.toThrow("unknown outcome");
  await expect(conversation.send("two",signal)).rejects.toThrow("unavailable");
  expect(execute).toHaveBeenCalledTimes(1);
 });
});
