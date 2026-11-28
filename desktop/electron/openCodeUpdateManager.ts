import { createHash } from "node:crypto";
import { createReadStream, createWriteStream, readFileSync } from "node:fs";
import { mkdir, mkdtemp, rename, rm, stat, writeFile } from "node:fs/promises";
import { execFile } from "node:child_process";
import { promisify } from "node:util";
import { Readable, Transform } from "node:stream";
import { pipeline } from "node:stream/promises";
import path from "node:path";
import { compareVersions } from "./updateCheck";

const upstream = "https://github.com/anomalyco/opencode";
const latestRelease = "https://api.github.com/repos/anomalyco/opencode/releases/latest";
const assetName = "opencode-windows-x64.zip";
const maximumArchive = 512 * 1024 * 1024;
const validVersion = /^v\d{1,4}\.\d{1,4}\.\d{1,4}$/;
const validDigest = /^[a-f0-9]{64}$/;
const exec = promisify(execFile);

export type RuntimeVersion = { version: string; binary: string; sha256: string };
export type RuntimeOffer = { version: string; url: string; sha256: string; size: number };
export type RuntimeProbe = (candidate: RuntimeVersion, directory: string) => Promise<void>;

type Release = {tag_name?:string; draft?:boolean; prerelease?:boolean; assets?:Array<{name:string;browser_download_url:string;digest?:string;size:number}>};

export function verifiedRuntimeOffer(release: Release, current: string): RuntimeOffer | undefined {
  const version = release.tag_name;
  if (!version || !validVersion.test(version) || release.draft || release.prerelease || compareVersions(version,current) <= 0) return;
  const expected = upstream + "/releases/download/" + version + "/" + assetName;
  const asset = release.assets?.find(item => item.name === assetName && item.browser_download_url === expected);
  const sha256 = asset?.digest?.startsWith("sha256:") ? asset.digest.slice("sha256:".length) : undefined;
  if (!asset || !asset.digest?.startsWith("sha256:") || !sha256 || !validDigest.test(sha256) ||
      !Number.isSafeInteger(asset.size) || asset.size < 1 || asset.size > maximumArchive) {
    throw new Error("官方 Windows x64 运行时缺少可信摘要或文件信息");
  }
  return {version,url:expected,sha256,size:asset.size};
}

async function digest(file: string) {
  const hash = createHash("sha256");
  for await (const chunk of createReadStream(file)) hash.update(chunk);
  return hash.digest("hex");
}

async function expand(archive:string,destination:string) {
  const system = process.env.SystemRoot || "C:\\Windows";
  await exec(path.join(system,"System32","WindowsPowerShell","v1.0","powershell.exe"),
    ["-NoProfile","-NonInteractive","-Command","$ErrorActionPreference='Stop'; Expand-Archive -LiteralPath $env:LCA_ARCHIVE -DestinationPath $env:LCA_EXPANDED"],
    {windowsHide:true,timeout:120_000,env:{...process.env,LCA_ARCHIVE:archive,LCA_EXPANDED:destination}});
}

export class OpenCodeUpdateManager {
  private readonly versions: string;
  private readonly pointer: string;
  private busy = false;

  constructor(data: string, private readonly baseline:RuntimeVersion, private readonly probe:RuntimeProbe,
              private readonly isExecuting:()=>boolean, private readonly request:typeof fetch=fetch,
              private readonly unpack:typeof expand=expand) {
    this.versions = path.join(data,"opencode-versions");
    this.pointer = path.join(this.versions,"active.json");
  }

  current(): RuntimeVersion {
    try {
      const value = JSON.parse(readFileSync(this.pointer,"utf8")) as {version?:string;sha256?:string};
      if (typeof value.version !== "string" || !validVersion.test(value.version) ||
          typeof value.sha256 !== "string" || !validDigest.test(value.sha256)) return this.baseline;
      return {version:value.version,sha256:value.sha256,binary:path.join(this.versions,value.version,"opencode.exe")};
    } catch { return this.baseline; }
  }

  isUpgrading() { return this.busy; }

  async checkForUpdates() {
    const reply = await this.request(latestRelease,{headers:{accept:"application/vnd.github+json"},redirect:"error",signal:AbortSignal.timeout(15_000)});
    if (!reply.ok) throw new Error("OpenCode release lookup HTTP "+reply.status);
    return verifiedRuntimeOffer(await reply.json() as Release,this.current().version);
  }

  async upgrade(offer:RuntimeOffer, stop:()=>Promise<void>) {
    if (this.busy || this.isExecuting()) throw new Error("请先停止当前执行再升级运行时");
    if (!validVersion.test(offer.version) || !validDigest.test(offer.sha256) ||
        offer.url !== upstream+"/releases/download/"+offer.version+"/"+assetName ||
        !Number.isSafeInteger(offer.size) || offer.size < 1 || offer.size > maximumArchive ||
        compareVersions(offer.version,this.current().version) <= 0) throw new Error("升级候选版本无效");
    this.busy = true;
    let stage:string|undefined;
    try {
      await mkdir(this.versions,{recursive:true});
      stage = await mkdtemp(path.join(this.versions,"candidate-"));
      const zip = path.join(stage,assetName);
      let location = new URL(offer.url);
      const signal = AbortSignal.timeout(180_000);
      let response:Response|undefined;
      for (let redirects=0; redirects<4; redirects++) {
        response = await this.request(location,{redirect:"manual",signal});
        if (response.status < 300 || response.status >= 400) break;
        const target = response.headers.get("location");
        await response.body?.cancel();
        if (!target) throw new Error("下载重定向缺少目标");
        location = new URL(target,location);
        if (location.protocol !== "https:" || location.username || location.password || location.port ||
            !["github.com","release-assets.githubusercontent.com","objects.githubusercontent.com"].includes(location.hostname)) throw new Error("升级下载来源不可信");
      }
      if (!response?.ok || !response.body) throw new Error("运行时下载失败");
      let received=0;
      const bound = new Transform({transform(chunk,_encoding,done){
        received += chunk.length;
        if (received > offer.size) done(new Error("运行时下载超过声明大小"));
        else done(null,chunk);
      }});
      await pipeline(Readable.fromWeb(response.body as Parameters<typeof Readable.fromWeb>[0]),bound,createWriteStream(zip,{flags:"wx"}),{signal});
      if (received !== offer.size || await digest(zip) !== offer.sha256) throw new Error("运行时 ZIP SHA256 校验失败");
      const directory = path.join(stage,"expanded");
      await this.unpack(zip,directory);
      const binary = path.join(directory,"opencode.exe");
      const info = await stat(binary);
      if (!info.isFile() || info.size > maximumArchive) throw new Error("升级归档未包含有效的 Windows 可执行文件");
      const sha256 = await digest(binary);
      await this.probe({version:offer.version,binary,sha256},path.join(stage,"compatibility"));
      if (this.isExecuting()) throw new Error("运行时执行状态已变化，请重新检查更新");
      await stop();
      const versionDirectory=path.join(this.versions,offer.version);
      await rename(directory,versionDirectory);
      const next = path.join(stage,"active.json");
      await writeFile(next,JSON.stringify({version:offer.version,sha256}),{flag:"wx"});
      await rename(next,this.pointer);
      return this.current();
    } finally {
      if (stage) await rm(stage,{recursive:true,force:true}).catch(()=>{});
      this.busy = false;
    }
  }

  async restoreBundled(stop:()=>Promise<void>) {
    if (this.busy || this.isExecuting()) throw new Error("请先停止当前执行再回到内置版本");
    this.busy = true;
    try {
      if (await digest(this.baseline.binary) !== this.baseline.sha256) throw new Error("内置运行时 SHA256 不匹配");
      await stop();
      await rm(this.pointer,{force:true});
      return this.current();
    } finally { this.busy = false; }
  }
}
