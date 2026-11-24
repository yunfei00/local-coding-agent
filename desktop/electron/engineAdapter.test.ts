import { describe, expect, it, vi } from "vitest";
import { EngineRouter, LegacyAdapter, OpenCodeAdapter } from "./engineAdapter";
describe("P1 engine contract", () => {
  it("creates deny-all sessions and blocks prompts", async () => {
    const request = vi.fn(async () => ({data: {id: "s"}}));
    const engine = new OpenCodeAdapter(request);
    expect(await engine.create("fixture", "test")).toBe("s");
    expect(request).toHaveBeenCalledWith("/api/session", "POST", {title:"test", permissions:[{action:"*",resource:"*",effect:"deny"}]});
    await expect(engine.send("s", "hello")).rejects.toThrow("disabled");
    expect(request).toHaveBeenCalledTimes(1);
  });
  it("defaults to legacy and rejects OpenCode routing", async () => {
    const send = vi.fn(async () => {});
    const legacy = new LegacyAdapter({create:async()=>"l",status:async()=>null,send,cancel:async()=>null});
    const router = new EngineRouter(legacy,new OpenCodeAdapter(async()=>null));
    expect(router.engine()).toBe(legacy);
    await expect(router.run({threadId:"t",engine:"opencode",sessionId:"s",projectRoot:"fixture"},"hello")).rejects.toThrow("disabled");
    expect(send).not.toHaveBeenCalled();
    await router.run({threadId:"t",engine:"legacy",sessionId:"l",projectRoot:"fixture"},"hello");
    expect(send).toHaveBeenCalledWith("l","hello");
  });
});
