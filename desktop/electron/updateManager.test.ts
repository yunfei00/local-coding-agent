import {it,expect,vi,afterEach} from 'vitest';
import http from 'node:http';
import https from 'node:https';
import {mkdtemp,readFile,writeFile,rm,readdir,symlink} from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import {createHash} from 'node:crypto';
import {UpdateManager,releaseOffer,checksumFor,assetDownloader,type UpdateState} from './updateManager';
import {compareVersions} from './updateCheck';

// Real loopback HTTP + real files + production streaming/hash code.
// Only OS executable opening is mocked; fixture bytes are never executed.
const binary=Buffer.from('isolated update download fixture; never execute\n'.repeat(3000));
const hash=createHash('sha256').update(binary).digest('hex');
const name='Local-Coding-Agent-1.0.1-x64-Setup.exe';
const portable='Local-Coding-Agent-1.0.1-x64-Portable.exe';
function metadata(){return {tag_name:'v1.0.1',body:'中文发布说明',assets:[name,portable,'SHA256SUMS.txt'].map(n=>({name:n,size:n.endsWith('.exe')?binary.length:200,browser_download_url:`https://github.com/yunfei00/local-coding-agent/releases/download/v1.0.1/${n}`}))};}
const roots:string[]=[],servers:http.Server[]=[];
afterEach(async()=>{for(const s of servers.splice(0)){s.closeAllConnections();await new Promise<void>(r=>s.close(()=>r()));}for(const d of roots.splice(0))await rm(d,{recursive:true,force:true});});
async function fixture(mode='normal',portableMode=false){
 const root=await mkdtemp(path.join(os.tmpdir(),'lca-plan-a-'));roots.push(root);
 const states:UpdateState[]=[],requests:string[]=[];
 const server=http.createServer((req,res)=>{
  requests.push(req.url||'');
  if(mode==='http'){res.writeHead(403);res.end();return;}
  if(mode==='network'){res.destroy();return;}
  if(req.url?.endsWith('SHA256SUMS.txt')){res.end(`${mode==='badHash'?'0'.repeat(64):hash}  ${mode==='missingSum'?'other.exe':name}\n${hash}  ${portable}\n`);return;}
  if(mode!=='unknown')res.setHeader('Content-Length',binary.length);
  let offset=0;
  const send=()=>{if(res.destroyed)return;if(offset>=binary.length){res.end();return;}res.write(binary.subarray(offset,offset+4096));offset+=4096;setTimeout(send,mode==='slow'?25:1);};send();
 });servers.push(server);await new Promise<void>(r=>server.listen(0,'127.0.0.1',r));
 const base=`http://127.0.0.1:${(server.address() as {port:number}).port}`;
 const transport=((url:URL,opts:https.RequestOptions,cb:(r:http.IncomingMessage)=>void)=>http.get(new URL(url.pathname,base),opts,cb)) as typeof https.get;
 const download=assetDownloader(transport),meta=metadata();if(mode==='unknown')meta.assets[0].size=0;
 const manager=new UpdateManager(root,'1.0.0',async()=>meta,download,{portable:portableMode,freeSpace:async()=>1e10,emit:s=>states.push(s)});
 return {root,states,requests,manager,meta,download};
}

it('SemVer compares stable, numeric prerelease and build metadata correctly',()=>{expect(compareVersions('1.0.0','1.0.0-rc.1')).toBe(1);expect(compareVersions('1.0.0-beta.2','1.0.0-beta.10')).toBe(-1);expect(compareVersions('1.0.0+build','1.0.0')).toBe(0);});
it('up to date or older is no offer',()=>{expect(releaseOffer('1.0.1',metadata())).toBeNull();expect(releaseOffer('2.0.0',metadata())).toBeNull();});
it('draft and prerelease are ignored',()=>{expect(releaseOffer('1.0.0',{...metadata(),draft:true})).toBeNull();expect(releaseOffer('1.0.0',{...metadata(),prerelease:true})).toBeNull();});
it('selects exact x64 Setup or Portable separately',()=>{expect(releaseOffer('1.0.0',metadata())?.installer.name).toBe(name);expect(releaseOffer('1.0.0',metadata(),true)?.installer.name).toBe(portable);});
it('missing and duplicate installer assets fail',()=>{const m=metadata();m.assets=m.assets.filter(a=>a.name!==name);expect(()=>releaseOffer('1.0.0',m)).toThrow();expect(()=>releaseOffer('1.0.0',{...metadata(),assets:[...metadata().assets,metadata().assets[0]]})).toThrow();});
it('only official repository HTTPS names are accepted, no traversal or external origin',()=>{for(const url of ['http://github.com/a','https://evil.example/a','https://github.com/other/repo/a','https://github.com/yunfei00/local-coding-agent/releases/download/v1.0.1/../evil.exe']){const m=metadata();m.assets[0].browser_download_url=url;expect(()=>releaseOffer('1.0.0',m)).toThrow();}});
it('missing SHA manifest fails before any download',()=>{const m=metadata();m.assets=m.assets.filter(a=>a.name!=='SHA256SUMS.txt');expect(()=>releaseOffer('1.0.0',m)).toThrow();});
it('malformed duplicate or missing checksum lines fail',()=>{for(const text of ['bad',`${hash}  ${name}\n${hash}  ${name}`,`${hash}  other.exe`,`${hash}  ../evil.exe`])expect(()=>checksumFor(text,name)).toThrow();});
it('check exposes actual available state and notes',async()=>{const f=await fixture();await f.manager.check();expect((await f.manager.status()).state).toBe('AVAILABLE');expect((await f.manager.status()).notes).toBe('中文发布说明');});
it('real streamed download emits byte progress and SHA verification states',async()=>{const f=await fixture();const ready=await f.manager.downloadUpdate();expect(ready.sha256).toBe(hash);expect(f.states.some(s=>s.state==='DOWNLOADING'&&s.bytes>0)).toBe(true);expect(f.states.some(s=>s.state==='VERIFYING')).toBe(true);expect((await f.manager.status()).state).toBe('READY_TO_INSTALL');expect((await f.manager.status()).bytes).toBe(binary.length);});
it('unknown total remains unknown rather than fabricated percentage',async()=>{const f=await fixture('unknown');await f.manager.downloadUpdate();expect(f.states.filter(s=>s.state==='DOWNLOADING').every(s=>s.total===undefined)).toBe(true);});
it('cancellation aborts real HTTP stream and removes partial files',async()=>{const f=await fixture('slow');const pending=f.manager.downloadUpdate();while(!f.states.some(s=>s.bytes>0))await new Promise(r=>setTimeout(r,5));f.manager.cancel();await expect(pending).rejects.toThrow();expect((await f.manager.status()).state).toBe('CANCELLED');const dirs=await readdir(path.join(f.root,'updates'));for(const d of dirs)expect((await readdir(path.join(f.root,'updates',d))).some(n=>n.endsWith('.partial'))).toBe(false);});
it('concurrent duplicate download is rejected',async()=>{const f=await fixture();const first=f.manager.downloadUpdate();await expect(f.manager.downloadUpdate()).rejects.toThrow('重复');await first;});
it('network failure is ERROR and cannot open an installer',async()=>{const f=await fixture('network');await expect(f.manager.downloadUpdate()).rejects.toThrow();const open=vi.fn();await expect(f.manager.openPackage(open)).rejects.toThrow();expect(open).not.toHaveBeenCalled();expect((await f.manager.status()).state).toBe('ERROR');});
it('HTTP 403 download produces a concrete HTTP error',async()=>{const f=await fixture('http');await expect(f.manager.downloadUpdate()).rejects.toThrow('HTTP 403');});
it('metadata HTTP 404/timeout is an actionable ERROR',async()=>{for(const error of ['HTTP 404','检查超时']){const f=await fixture();const manager=new UpdateManager(f.root,'1.0.0',async()=>{throw Error(error);});await expect(manager.check()).rejects.toThrow(error);expect((await manager.status()).state).toBe('ERROR');}});
it('insufficient disk space prevents network transfer',async()=>{const f=await fixture();const manager=new UpdateManager(f.root,'1.0.0',async()=>f.meta,f.download,{freeSpace:async()=>1});await expect(manager.downloadUpdate()).rejects.toThrow('磁盘空间不足');expect(f.requests).toEqual([]);});
it('bad SHA blocks manual opening and deletes bad file',async()=>{const f=await fixture('badHash');await expect(f.manager.downloadUpdate()).rejects.toThrow('SHA256');const open=vi.fn();await expect(f.manager.openPackage(open)).rejects.toThrow();expect(open).not.toHaveBeenCalled();});
it('missing target checksum does not download binary',async()=>{const f=await fixture('missingSum');await expect(f.manager.downloadUpdate()).rejects.toThrow('未包含');expect(f.requests.length).toBe(1);});
it('post-download tampering is rejected again at explicit open',async()=>{const f=await fixture();await f.manager.downloadUpdate();const dir=(await readdir(path.join(f.root,'updates'))).find(n=>n!=='ready.json')!;await writeFile(path.join(f.root,'updates',dir,name),'tampered');const open=vi.fn();await expect(f.manager.openPackage(open)).rejects.toThrow('发生改变');expect(open).not.toHaveBeenCalled();});
it('verified package opens only after explicit user action; no task or quit callbacks',async()=>{const f=await fixture();const open=vi.fn(async()=>''),folder=vi.fn();await f.manager.downloadUpdate();expect(open).not.toHaveBeenCalled();await f.manager.openPackage(open);await f.manager.openFolder(folder);expect(open).toHaveBeenCalledTimes(1);expect(folder).toHaveBeenCalledTimes(1);expect(await readFile(open.mock.calls[0][0])).toEqual(binary);});
it('Portable downloads its own asset and gives manual replacement instructions',async()=>{const f=await fixture('normal',true);await f.manager.downloadUpdate();expect((await f.manager.status()).message).toContain('手动替换');expect(f.requests.some(p=>p.endsWith(portable))).toBe(true);});
it('cache is restored only after actual hash verification on restart',async()=>{const f=await fixture();await f.manager.downloadUpdate();const second=new UpdateManager(f.root,'1.0.0');expect((await second.status()).state).toBe('READY_TO_INSTALL');});
it('malformed cache and path traversal cannot become installable or overwrite unrelated files',async()=>{const f=await fixture();await f.manager.downloadUpdate();const record=path.join(f.root,'updates','ready.json'),saved=JSON.parse(await readFile(record,'utf8'));saved.file=path.join(f.root,'unrelated.exe');await writeFile(saved.file,'personal data');await writeFile(record,JSON.stringify(saved));const second=new UpdateManager(f.root,'1.0.0');expect((await second.status()).state).toBe('ERROR');expect(await readFile(saved.file,'utf8')).toBe('personal data');});
it('failed transfer can be retried, preserving the active application',async()=>{const f=await fixture('badHash');await expect(f.manager.downloadUpdate()).rejects.toThrow();const good=await fixture();const retry=new UpdateManager(f.root,'1.0.0',async()=>good.meta,good.download,{freeSpace:async()=>1e10});await retry.downloadUpdate();expect((await retry.status()).state).toBe('READY_TO_INSTALL');});
it('filesystem links cannot redirect update cache outside app data',async()=>{const f=await fixture();const outside=await mkdtemp(path.join(os.tmpdir(),'lca-unrelated-'));roots.push(outside);await symlink(outside,path.join(f.root,'updates'),process.platform==='win32'?'junction':'dir');await expect(f.manager.downloadUpdate()).rejects.toThrow('链接');expect(await readdir(outside)).toEqual([]);});
it('consent version cannot silently change before download',async()=>{const f=await fixture();await expect(f.manager.downloadUpdate('1.0.2')).rejects.toThrow('版本已变化');expect(f.requests).toEqual([]);});
it('missing cached binary is ERROR rather than ready after restart',async()=>{const f=await fixture();await f.manager.downloadUpdate();const saved=JSON.parse(await readFile(path.join(f.root,'updates/ready.json'),'utf8'));await rm(saved.file);const next=new UpdateManager(f.root,'1.0.0');expect((await next.status()).state).toBe('ERROR');});
it('corrupt cache errors never echo its secret-like content',async()=>{const f=await fixture();await f.manager.downloadUpdate();await writeFile(path.join(f.root,'updates/ready.json'),'private-data-not-valid-json');const next=new UpdateManager(f.root,'1.0.0');const state=await next.status();expect(state.state).toBe('ERROR');expect(state.error).not.toContain('private-data');});
