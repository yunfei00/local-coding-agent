import {describe,it,expect} from "vitest";
import {InteractiveTurnQueue} from "./interactiveTurnQueue";
describe("interactive turn queue",()=>{
 it("accepts input only while waiting and enforces turn limit",async()=>{
  const q=new InteractiveTurnQueue(1),signal=new AbortController().signal;
  expect(()=>q.submit("early")).toThrow();
  const pending=q.next(signal);q.submit("hello");expect(await pending).toBe("hello");expect(await q.next(signal)).toBeNull();
 });
 it("cancels waiting without replay",async()=>{
  const q=new InteractiveTurnQueue(),controller=new AbortController();
  const pending=q.next(controller.signal);controller.abort();await expect(pending).rejects.toThrow("interrupted");expect(()=>q.submit("late")).toThrow();
 });
 it("finishes normally when closed",async()=>{
  const q=new InteractiveTurnQueue(),pending=q.next(new AbortController().signal);q.close();expect(await pending).toBeNull();
 });
});
