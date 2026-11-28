import { afterEach, describe, expect, it, vi } from "vitest";
import { createHash } from "node:crypto";
import { mkdir, mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { OpenCodeUpdateManager, verifiedRuntimeOffer } from "./openCodeUpdateManager";

const folders:string[]=[];
const fixture=Buffer.from("fixture archive");
const hash=(value:Buffer)=>createHash("sha256").update(value).digest("hex");
const offer={version:"v2.2.7",url:"https://github.com/anomalyco/opencode/releases/download/v2.2.7/opencode-windows-x64.zip",sha256:hash(fixture),size:fixture.length};
const metadata={tag_name:offer.version,assets:[{name:"opencode-windows-x64.zip",browser_download_url:offer.url,digest:"sha256:"+offer.sha256,size:offer.size}]};

afterEach(async()=>{for(const root of folders.splice(0)) await rm(root,{recursive:true,force:true});});

async function settings() {
  const root=await mkdtemp(path.join(os.tmpdir(),"lca-runtime-upgrade-"));
  folders.push(root);
  const binary=path.join(root,"bundled.exe");
  await writeFile(binary,fixture);
  const baseline={version:"v2.2.6",binary,sha256:hash(fixture)};
  const probe=vi.fn(async(candidate:{binary:string})=>{expect(await readFile(candidate.binary)).toEqual(fixture);});
  const request=vi.fn(async(url:URL|string)=>String(url).includes("/latest") ? Response.json(metadata) : new Response(fixture));
  const unpack=vi.fn(async(zip:string,target:string)=>{await mkdir(target);await writeFile(path.join(target,"opencode.exe"),await readFile(zip));});
  const busy=vi.fn(()=>false);
  const manager=new OpenCodeUpdateManager(root,baseline,probe,busy,request,unpack);
  return {root,baseline,probe,request,busy,manager,unpack};
}

describe("independent OpenCode update",()=>{
  it("uses only the pinned repository's newer stable x64 release with a SHA256",()=>{
    expect(verifiedRuntimeOffer(metadata,"v2.2.6")).toEqual(offer);
    expect(verifiedRuntimeOffer(metadata,"v2.2.7")).toBeUndefined();
    expect(verifiedRuntimeOffer({...metadata,prerelease:true},"v2.2.6")).toBeUndefined();
    expect(()=>verifiedRuntimeOffer({...metadata,assets:[{...metadata.assets[0],digest:"bad"}]},"v2.2.6")).toThrow("摘要");
  });
  it("checks without download and writes selection only after actual verification",async()=>{
    const {manager,request,probe,root,baseline}=await settings();
    expect(await manager.checkForUpdates()).toEqual(offer);
    expect(request).toHaveBeenCalledTimes(1);
    expect(manager.current()).toEqual(baseline);
    const stop=vi.fn(async()=>{});
    const active=await manager.upgrade(offer,stop);
    expect(active.version).toBe(offer.version);
    expect(stop).toHaveBeenCalledOnce();
    expect(probe).toHaveBeenCalledOnce();
    expect(new OpenCodeUpdateManager(root,baseline,probe,()=>false).current()).toEqual(active);
    expect(await manager.restoreBundled(stop)).toEqual(baseline);
    expect(await readFile(active.binary)).toEqual(fixture);
  });
  it("rejects checksum mismatch before extraction and preserves current",async()=>{
    const {manager,baseline,unpack}=await settings();
    await expect(manager.upgrade({...offer,sha256:"0".repeat(64)},async()=>{})).rejects.toThrow("SHA256");
    expect(unpack).not.toHaveBeenCalled();
    expect(manager.current()).toEqual(baseline);
    expect(manager.isUpgrading()).toBe(false);
  });
  it("does not stop the current runtime if API or protocol probe fails",async()=>{
    const {manager,baseline,probe}=await settings();
    probe.mockRejectedValueOnce(new Error("SSE 不兼容"));
    const stop=vi.fn(async()=>{});
    await expect(manager.upgrade(offer,stop)).rejects.toThrow("SSE");
    expect(stop).not.toHaveBeenCalled();
    expect(manager.current()).toEqual(baseline);
  });
  it("denies concurrent task ownership before network traffic",async()=>{
    const {manager,busy,request}=await settings();
    busy.mockReturnValue(true);
    await expect(manager.upgrade(offer,async()=>{})).rejects.toThrow("停止");
    expect(request).not.toHaveBeenCalled();
  });
  it("rejects non-official redirect targets",async()=>{
    const {manager,request,unpack}=await settings();
    request.mockResolvedValueOnce(new Response(null,{status:302,headers:{location:"https://example.test/engine.zip"}}));
    await expect(manager.upgrade(offer,async()=>{})).rejects.toThrow("来源不可信");
    expect(unpack).not.toHaveBeenCalled();
  });
});
