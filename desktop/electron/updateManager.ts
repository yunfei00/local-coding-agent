import https from 'node:https';
import path from 'node:path';
import {createHash,randomUUID} from 'node:crypto';
import {createReadStream,createWriteStream,existsSync} from 'node:fs';
import {mkdir,readFile,rename,unlink,writeFile,stat,statfs,realpath,lstat} from 'node:fs/promises';
import {Transform} from 'node:stream';
import {pipeline} from 'node:stream/promises';
import {compareVersions,requestJson,type ReleaseMetadata} from './updateCheck';

const REPOSITORY='yunfei00/local-coding-agent';
const API=`https://api.github.com/repos/${REPOSITORY}/releases/latest`;
const MAX=600*1024*1024;
type Asset={name:string;browser_download_url:string;size:number};
export type Offer={version:string;notes:string;installer:Asset;checksums:Asset};
export type UpdateState={state:'IDLE'|'CHECKING'|'UP_TO_DATE'|'AVAILABLE'|'DOWNLOADING'|'VERIFYING'|'READY_TO_INSTALL'|'ERROR'|'CANCELLED';current_version:string;platform:string;source:string;version?:string;notes?:string;bytes:number;total?:number;sha256?:string;error?:string;portable:boolean;message?:string};
export type DownloadOptions={signal?:AbortSignal;progress?:(bytes:number,total?:number)=>void;total?:number};
export type Download=(url:string,file:string,limit:number,options?:DownloadOptions)=>Promise<void>;

export function installedUpdateSupported(executable:string,runtime:{packaged:boolean;platform:string;arch:string;portable:boolean}):boolean {
 return runtime.packaged&&runtime.platform==='win32'&&runtime.arch==='x64'&&!runtime.portable&&['Uninstall LocalCodingAgent.exe','Uninstall Local Coding Agent.exe'].some(n=>existsSync(path.join(path.dirname(executable),n)));
}
export function releaseOffer(current:string,metadata:ReleaseMetadata,portable=false):Offer|null {
 if(metadata.draft||metadata.prerelease)return null;
 const tag=metadata.tag_name||'';
 if(!/^v(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)$/.test(tag))throw Error('正式更新版本信息无效');
 const version=tag.slice(1);if(compareVersions(version,current)<=0)return null;
 const asset=(name:string)=>{
  const found=metadata.assets?.filter(a=>a.name===name)||[];
  if(found.length!==1)throw Error('更新缺少唯一 Windows x64 安装包或校验清单');
  const value=found[0],url=new URL(value.browser_download_url);
  if(url.protocol!=='https:'||url.hostname!=='github.com'||url.port||url.username||url.password||url.search||url.hash||decodeURIComponent(url.pathname)!==`/${REPOSITORY}/releases/download/${tag}/${name}`||!Number.isSafeInteger(value.size)||value.size<0||value.size>MAX)throw Error('更新资源来源、大小或名称无效');
  return value;
 };
 return {version,notes:String(metadata.body||'').slice(0,20000),installer:asset(`Local-Coding-Agent-${version}-x64-${portable?'Portable':'Setup'}.exe`),checksums:asset('SHA256SUMS.txt')};
}
export function checksumFor(text:string,name:string):string {
 const records=text.trim().split(/\r?\n/).map(line=>/^([0-9a-f]{64})  ([A-Za-z0-9._-]+)$/.exec(line));
 if(records.some(r=>!r))throw Error('SHA256 清单格式无效');
 const matches=records.filter(r=>r?.[2]===name);if(matches.length!==1)throw Error('SHA256 清单未包含唯一安装包');return matches[0]![1];
}
export async function digestFile(file:string){const h=createHash('sha256');for await(const c of createReadStream(file))h.update(c);return h.digest('hex');}

export function assetDownloader(get:typeof https.get=https.get):Download{return async(url,file,limit,options={})=>{
 const temporary=file+'.partial',deadline=Date.now()+300000;
 async function transfer(address:string,redirects:number):Promise<void>{
  const parsed=new URL(address);
  if(parsed.protocol!=='https:'||parsed.username||parsed.password||parsed.port||!['github.com','release-assets.githubusercontent.com','objects.githubusercontent.com'].includes(parsed.hostname))throw Error('更新下载跳转来源不受信任');
  await new Promise<void>((resolve,reject)=>{
   const request=get(parsed,{signal:options.signal,headers:{'User-Agent':'Local-Coding-Agent-Updater'}},response=>{
    if([301,302,303,307,308].includes(response.statusCode||0)){
     response.resume();if(redirects>=5||!response.headers.location){reject(Error('更新跳转次数超限'));return;}
     transfer(new URL(response.headers.location,parsed).href,redirects+1).then(resolve,reject);return;
    }
    if(response.statusCode!==200){response.resume();reject(Error(`更新下载 HTTP ${response.statusCode}`));return;}
    let bytes=0;const length=Number(response.headers['content-length']);
    const total=options.total||(Number.isSafeInteger(length)&&length>0?length:undefined);
    if(total&&total>limit){response.destroy();reject(Error('更新下载超过大小上限'));return;}
    const bounded=new Transform({transform(chunk,_encoding,callback){bytes+=chunk.length;options.progress?.(bytes,total);callback(bytes>limit?Error('更新下载超过大小上限'):null,chunk);}});
    pipeline(response,bounded,createWriteStream(temporary,{flags:'wx'}),{signal:options.signal}).then(()=>resolve(),reject);
   });
   request.setTimeout(60000,()=>request.destroy(Error('更新下载超时')));
   const timer=setTimeout(()=>request.destroy(Error('更新下载总时间超限')),Math.max(1,deadline-Date.now()));
   request.on('close',()=>clearTimeout(timer));request.on('error',reject);
  });
 }
 try{await transfer(url,0);options.signal?.throwIfAborted();await rename(temporary,file);}catch(e){await unlink(temporary).catch(()=>{});throw e;}
};}
export const downloadAsset=assetDownloader();

type Options={portable?:boolean;platform?:string;emit?:(state:UpdateState)=>void;freeSpace?:(directory:string)=>Promise<number>};
export class UpdateManager {
 private ready?:{offer:Offer;file:string;sha256:string};
 private busy=false;private controller?:AbortController;private restored=false;
 private value:UpdateState;
 constructor(private root:string,private current:string,private fetchMetadata=()=>requestJson(API,10000),private download:Download=downloadAsset,private options:Options={}){
  this.value={state:'IDLE',current_version:current,platform:options.platform||`${process.platform}-${process.arch}`,source:`https://github.com/${REPOSITORY}/releases`,bytes:0,portable:!!options.portable};
 }
 private set(change:Partial<UpdateState>){this.value={...this.value,...change};this.options.emit?.({...this.value});}
 private fail(error:unknown){this.set({state:this.controller?.signal.aborted?'CANCELLED':'ERROR',error:this.controller?.signal.aborted?undefined:String(error instanceof Error?error.message:error).slice(0,500)});}
 async status(){if(!this.restored&&!this.busy){this.restored=true;if(this.value.state==='IDLE')await this.restore();}return {...this.value};}
 async check(){
  if(this.busy)throw Error('正在处理更新，请勿重复操作');
  this.busy=true;this.set({state:'CHECKING',error:undefined});
  try{const metadata=await this.fetchMetadata();const offer=releaseOffer(this.current,metadata,this.options.portable);this.set({state:offer?'AVAILABLE':'UP_TO_DATE',version:offer?.version||(!metadata.draft&&!metadata.prerelease?metadata.tag_name?.slice(1):undefined),notes:offer?.notes,bytes:0,sha256:undefined});return offer;}
  catch(e){this.fail(e);throw e;}finally{this.busy=false;}
 }
 cancel(){this.controller?.abort();}
 get readyVersion(){return this.ready?.offer.version;}
 async downloadUpdate(expectedVersion?:string){
  if(this.busy)throw Error('正在处理更新，请勿重复操作');
  const offer=await this.check();if(!offer)throw Error('当前没有可用更新');
  if(expectedVersion&&offer.version!==expectedVersion)throw Error('更新版本已变化，请重新查看说明并确认');
  if(this.busy)throw Error('正在处理更新，请勿重复操作');
  this.busy=true;this.restored=true;this.ready=undefined;this.controller=new AbortController();
  const signal=this.controller.signal;let file:string|undefined;
  try{
   const cache=path.join(this.root,'updates');await mkdir(cache,{recursive:true});
   if((await lstat(cache)).isSymbolicLink()||await realpath(cache)!==path.join(await realpath(this.root),'updates'))throw Error('更新缓存链接无效');
   const free=await (this.options.freeSpace||(async(d:string)=>{const s=await statfs(d);return Number(s.bavail)*Number(s.bsize);}))(cache);
   if(free<(offer.installer.size||MAX)+1024*1024+16*1024*1024)throw Error('磁盘空间不足，未开始下载');
   const directory=path.join(cache,offer.version+'-'+randomUUID());await mkdir(directory);
   this.set({state:'DOWNLOADING',version:offer.version,notes:offer.notes,bytes:0,total:offer.installer.size||undefined,sha256:undefined,error:undefined});
   const sums=path.join(directory,'SHA256SUMS.txt');await this.download(offer.checksums.browser_download_url,sums,1024*1024,{signal});
   const sha256=checksumFor(await readFile(sums,'utf8'),offer.installer.name);file=path.join(directory,offer.installer.name);
   let last=0;
   await this.download(offer.installer.browser_download_url,file,offer.installer.size||MAX,{signal,total:offer.installer.size||undefined,progress:(bytes,total)=>{if(Date.now()-last>100){last=Date.now();this.set({bytes,total});}}});
   signal.throwIfAborted();this.set({state:'VERIFYING',bytes:(await stat(file)).size});
   if((offer.installer.size&&(await stat(file)).size!==offer.installer.size)||await digestFile(file)!==sha256)throw Error('更新包 SHA256 或文件大小校验失败');
   signal.throwIfAborted();this.ready={offer,file,sha256};
   const receipt=path.join(cache,'ready.json'),temporary=receipt+'.'+randomUUID()+'.tmp';
   await writeFile(temporary,JSON.stringify(this.ready),{flag:'wx'});await rename(temporary,receipt);
   signal.throwIfAborted();
   this.set({state:'READY_TO_INSTALL',sha256,message:this.options.portable?'便携版已下载并通过校验，请退出软件后手动替换。':'安装包已下载并通过校验，请关闭软件后手动安装新版本。'});
   return {ready:true,version:offer.version,sha256,notes:offer.notes};
  }catch(e){this.ready=undefined;if(file)await unlink(file).catch(()=>{});this.fail(e);throw e;}finally{this.busy=false;this.controller=undefined;}
 }
 private async checked(){
  if(this.busy||!this.ready||this.value.state!=='READY_TO_INSTALL')throw Error('请先下载并校验更新包');
  const {file,offer,sha256}=this.ready,cache=path.resolve(this.root,'updates');
  const relative=path.relative(cache,file),parts=relative.split(path.sep);
  if(parts.length!==2||parts.some(p=>!p||p==='..')||parts[1]!==offer.installer.name||!/^\d+\.\d+\.\d+-[0-9a-f-]{36}$/.test(parts[0]))throw Error('更新缓存路径无效');
  if((await lstat(file)).isSymbolicLink()||await realpath(path.dirname(file))!==path.join(await realpath(cache),parts[0]))throw Error('更新缓存链接无效');
  if((await stat(file)).size<=0||await digestFile(file)!==sha256)throw Error('更新包在下载后发生改变，禁止打开');
  return file;
 }
 private async restore(){
  let recordFound=false;
  try{
   const cache=path.join(this.root,'updates'),record=path.join(cache,'ready.json');const info=await lstat(record);recordFound=true;
   if(info.isSymbolicLink()||(await lstat(cache)).isSymbolicLink())throw Error('更新缓存链接无效');
   if(info.size>65536)throw Error('更新缓存记录过大');
   let saved;try{saved=JSON.parse(await readFile(record,'utf8'));}catch{throw Error('更新缓存记录损坏，请重新下载');}
   const offer=releaseOffer(this.current,{tag_name:'v'+saved.offer.version,body:saved.offer.notes,assets:[saved.offer.installer,saved.offer.checksums]},this.options.portable);
   if(!offer)return;
   if(!/^[a-f0-9]{64}$/.test(saved.sha256))throw Error('更新缓存校验信息无效');
   this.ready={offer,file:saved.file,sha256:saved.sha256};this.value.state='READY_TO_INSTALL';await this.checked();
   this.set({state:'READY_TO_INSTALL',version:offer.version,notes:offer.notes,sha256:saved.sha256,message:'已恢复并重新校验更新缓存；请关闭软件后手动安装。'});
  }catch(e){this.ready=undefined;if((e as NodeJS.ErrnoException).code==='ENOENT'&&!recordFound)this.set({state:'IDLE'});else this.fail(e);}
 }
 async openPackage(open:(file:string)=>Promise<string>){
  try{const file=await this.checked();const error=await open(file);if(error)throw Error(error);return {opened:true};}catch(e){this.fail(e);throw e;}
 }
 async openFolder(open:(file:string)=>void){try{open(await this.checked());return {opened:true};}catch(e){this.fail(e);throw e;}}
}
