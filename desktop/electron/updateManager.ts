import https from 'node:https';
import path from 'node:path';
import {createHash,randomUUID} from 'node:crypto';
import {createReadStream, createWriteStream} from 'node:fs';
import {mkdir,readFile,rename,unlink,writeFile,stat} from 'node:fs/promises';
import {Transform} from 'node:stream';
import {pipeline} from 'node:stream/promises';
import {compareVersions,requestJson,type ReleaseMetadata} from './updateCheck';

const REPOSITORY='yunfei00/local-coding-agent';
const API=`https://api.github.com/repos/${REPOSITORY}/releases/latest`;
type Asset={name:string;browser_download_url:string;size:number};
export type Offer={version:string;notes:string;installer:Asset;checksums:Asset};
type Download=(url:string,file:string,limit:number)=>Promise<void>;

export function releaseOffer(current:string,metadata:ReleaseMetadata):Offer|null {
  const tag=metadata.tag_name||'';
  if(metadata.draft||metadata.prerelease||!/^v\d+\.\d+\.\d+$/.test(tag))throw new Error('正式更新版本信息无效');
  const version=tag.slice(1);
  if(compareVersions(version,current)<=0)return null;
  const expected=`Local-Coding-Agent-${version}-x64-Setup.exe`;
  const asset=(name:string)=>{
    const found=metadata.assets?.filter(a=>a.name===name)||[];
    if(found.length!==1)throw new Error('更新缺少唯一 Windows x64 安装包或校验清单');
    const value=found[0],url=new URL(value.browser_download_url);
    if(url.protocol!=='https:'||url.hostname!=='github.com'||url.port||url.username||url.password||url.search||url.hash||
      decodeURIComponent(url.pathname)!==`/${REPOSITORY}/releases/download/${tag}/${name}`||!Number.isSafeInteger(value.size)||value.size<=0||value.size>600*1024*1024)throw new Error('更新资源来源、大小或名称无效');
    return value;
  };
  return {version,notes:String(metadata.body||'').slice(0,20000),installer:asset(expected),checksums:asset('SHA256SUMS.txt')};
}

export function checksumFor(text:string,name:string):string {
  const records=text.trim().split(/\r?\n/).map(line=>/^([0-9a-f]{64})  ([A-Za-z0-9._-]+)$/.exec(line));
  if(records.some(r=>!r))throw new Error('SHA256 清单格式无效');
  const entries=records.filter(r=>r?.[2]===name);
  if(entries.length!==1)throw new Error('SHA256 清单未包含唯一安装包');
  return entries[0]![1];
}

export async function digestFile(file:string):Promise<string> {
  const digest=createHash('sha256');
  for await(const chunk of createReadStream(file))digest.update(chunk);
  return digest.digest('hex');
}

export const downloadAsset:Download=async(url,file,limit)=>{
  const temporary=file+'.partial';
  const deadline=Date.now()+300000;
  async function download(address:string,redirects:number):Promise<void> {
    const parsed=new URL(address);
    if(parsed.protocol!=='https:'||parsed.username||parsed.password||parsed.port||!['github.com','release-assets.githubusercontent.com','objects.githubusercontent.com'].includes(parsed.hostname))throw new Error('更新下载跳转来源不受信任');
    await new Promise<void>((resolve,reject)=>{
      const request=https.get(parsed,{headers:{'User-Agent':'Local-Coding-Agent-Updater'}},response=>{
        if([301,302,303,307,308].includes(response.statusCode||0)) {
          response.resume();
          if(redirects>=5||!response.headers.location){reject(new Error('更新跳转次数超限'));return;}
          download(new URL(response.headers.location,parsed).href,redirects+1).then(resolve,reject);return;
        }
        if(response.statusCode!==200){response.resume();reject(new Error(`更新下载 HTTP ${response.statusCode}`));return;}
        let bytes=0;
        const bounded=new Transform({transform(chunk,_encoding,callback){bytes+=chunk.length;callback(bytes>limit?new Error('更新下载超过大小上限'):null,chunk);}});
        pipeline(response,bounded,createWriteStream(temporary,{flags:'wx'})).then(()=>resolve(),reject);
      });
      request.setTimeout(60000,()=>request.destroy(new Error('更新下载超时')));
      const timer=setTimeout(()=>request.destroy(new Error('更新下载总时间超限')),Math.max(1,deadline-Date.now()));
      request.on('close',()=>clearTimeout(timer));
      request.on('error',reject);
    });
  }
  try {await download(url,0);await rename(temporary,file);}
  catch(error){await unlink(temporary).catch(()=>{});throw error;}
};

export class UpdateManager {
  private ready?:{offer:Offer;file:string;sha256:string};
  private busy=false;
  constructor(private root:string,private current:string,private fetchMetadata=()=>requestJson(API,10000),private download:Download=downloadAsset){}

  async check(){return releaseOffer(this.current,await this.fetchMetadata());}

  get readyVersion(){return this.ready?.offer.version;}

  async downloadUpdate(expectedVersion?:string){
    if(this.busy)throw new Error('正在处理更新，请勿重复操作');
    this.busy=true;
    this.ready=undefined;
    try {
      const offer=await this.check();if(!offer)throw new Error('当前没有可用更新');
      if(expectedVersion&&offer.version!==expectedVersion)throw new Error('更新版本已变化，请重新查看说明并确认');
      const directory=path.join(this.root,'updates',offer.version+'-'+randomUUID());await mkdir(directory,{recursive:true});
      const sums=path.join(directory,'SHA256SUMS.txt');
      await this.download(offer.checksums.browser_download_url,sums,1024*1024);
      const sha256=checksumFor(await readFile(sums,'utf8'),offer.installer.name);
      const file=path.join(directory,offer.installer.name);
      try {
        await this.download(offer.installer.browser_download_url,file,offer.installer.size);
        if((await stat(file)).size!==offer.installer.size||await digestFile(file)!==sha256)throw new Error('更新包 SHA256 或文件大小校验失败');
      }catch(error){await unlink(file).catch(()=>{});throw error;}
      this.ready={offer,file,sha256};
      return {ready:true,version:offer.version,sha256,notes:offer.notes};
    }finally{this.busy=false;}
  }

  async install(prepare:()=>Promise<unknown>,launch:(file:string)=>Promise<void>){
    if(this.busy||!this.ready)throw new Error('请先下载并校验更新包');
    this.busy=true;
    const {file,sha256,offer}=this.ready;
    try {
      if(await digestFile(file)!==sha256)throw new Error('更新包在下载后发生改变，禁止安装');
      const backup=await prepare();
      // A spawn is not proof of installation; next startup checks actual version.
      await writeFile(path.join(this.root,'pending-update.json'),JSON.stringify({version:offer.version,backup,started_at:new Date().toISOString(),state:'pending'}),'utf8');
      await launch(file);
      return {started:true,version:offer.version,verified_installation:false};
    }finally{this.busy=false;}
  }
}

export async function updateReceipt(root:string,current:string){
  try {
    const record=JSON.parse(await readFile(path.join(root,'pending-update.json'),'utf8'));
    return {version:record.version,verified:record.version===current,backup:record.backup,
      message:record.version===current?'更新后实际版本已确认；数据备份保留':'上次更新尚未确认成功；用户数据和备份保留，可重试安装'};
  }catch(error){
    if((error as NodeJS.ErrnoException).code==='ENOENT')return null;
    return {verified:false,message:'更新记录无法读取；未删除用户数据，请导出诊断'};
  }
}
