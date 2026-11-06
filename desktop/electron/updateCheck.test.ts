import { describe, expect, it,vi } from "vitest";
import https from 'node:https';
import {EventEmitter} from 'node:events';

import {
  checkForUpdates,
  compareVersions,
  releaseResult,requestJson
} from "./updateCheck";

describe("manual update check policy", () => {
  it('mid-response interruption is handled without an uncaught main-process error',async()=>{
    const spy=vi.spyOn(https,'get').mockImplementation(((...args:unknown[])=>{
      const request=Object.assign(new EventEmitter(),{setTimeout:vi.fn(),destroy:vi.fn()});
      queueMicrotask(()=>{const response=Object.assign(new EventEmitter(),{setEncoding:vi.fn(),statusCode:200});(args[2] as (r:unknown)=>void)(response);response.emit('data','{');response.emit('aborted');response.emit('error',Error('connection reset'));request.emit('close');});
      return request;
    }) as unknown as typeof https.get);
    try{await expect(requestJson('https://api.github.com/repos/yunfei00/local-coding-agent/releases/latest',1000)).rejects.toThrow('连接中断');}finally{spy.mockRestore();}
  });
  it("compares semantic versions", () => {
    expect(compareVersions("0.2.0", "0.1.0")).toBe(1);
    expect(compareVersions("v0.1.0", "0.1.0")).toBe(0);
    expect(compareVersions("0.1.0", "0.2.0")).toBe(-1);
  });

  it("reports an available release without install capabilities", () => {
    const result = releaseResult("0.1.0", {
      tag_name: "v0.2.0",
      html_url:
        "https://github.com/yunfei00/local-coding-agent/releases/tag/v0.2.0"
    });

    expect(result.ok).toBe(true);
    expect(result.update_available).toBe(true);
    expect(result.latest_version).toBe("0.2.0");
    expect(result.automatic).toBe(false);
    expect(result.can_auto_download).toBe(false);
    expect(result.can_auto_install).toBe(false);
  });

  it("does not treat an older release as an update", () => {
    const result = releaseResult("0.2.0", {
      tag_name: "v0.1.0",
      html_url:
        "https://github.com/yunfei00/local-coding-agent/releases/tag/v0.1.0"
    });

    expect(result.ok).toBe(true);
    expect(result.update_available).toBe(false);
  });

  it("rejects draft or prerelease metadata for the stable channel", () => {
    expect(
      releaseResult("0.1.0", {
        tag_name: "v0.2.0-beta.1",
        prerelease: true
      }).ok
    ).toBe(false);
    expect(
      releaseResult("0.1.0", {
        tag_name: "v0.2.0",
        draft: true
      }).ok
    ).toBe(false);
  });

  it("fails safely when offline", async () => {
    const result = await checkForUpdates("0.1.0", {
      url: "https://127.0.0.1:1/releases/latest",
      timeoutMs: 100
    });

    expect(result.ok).toBe(false);
    expect(result.update_available).toBe(false);
    expect(result.error).toBeTruthy();
    expect(result.automatic).toBe(false);
    expect(result.can_auto_download).toBe(false);
    expect(result.can_auto_install).toBe(false);
  });
});
