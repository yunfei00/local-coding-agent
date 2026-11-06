import {describe,it,expect,vi,afterEach} from 'vitest';
import {mkdtemp,readFile,writeFile,rm,readdir} from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import {createHash} from 'node:crypto';
import {UpdateManager,releaseOffer,checksumFor,updateReceipt} from './updateManager';

const binary=Buffer.from('isolated installer fixture, never executed');
const hash=createHash('sha256').update(binary).digest('hex');
const name='Local-Coding-Agent-1.0.1-x64-Setup.exe';
function metadata(){return {tag_name:'v1.0.1',body:'中文更新说明',assets:[name,'SHA256SUMS.txt'].map(n=>({name:n,size:n===name?binary.length:200,browser_download_url:`https://github.com/yunfei00/local-coding-agent/releases/download/v1.0.1/${n}`}))};}
const roots:string[]=[];
afterEach(async()=>{for(const root of roots.splice(0))await rm(root,{recursive:true,force:true});});
async function fixture(overrides:{badHash?:boolean;network?:boolean}={}){
 const root=await mkdtemp(path.join(os.tmpdir(),'lca-updater-test-'));roots.push(root);
 const download=vi.fn(async(url:string,file:string)=>{
   if(overrides.network)throw new Error('network unavailable');
   await writeFile(file,url.endsWith('SHA256SUMS.txt')?`${overrides.badHash?'a'.repeat(64):hash}  ${name}\n`:binary);
 });
 return {root,download,manager:new UpdateManager(root,'1.0.0',async()=>metadata(),download)};
}

describe('Windows x64 consent-based updater',()=>{
 it('returns no offer for current/older versions and rejects prerelease',()=>{
   expect(releaseOffer('1.0.1',metadata())).toBeNull();
   expect(releaseOffer('2.0.0',metadata())).toBeNull();
   expect(()=>releaseOffer('1.0.0',{...metadata(),prerelease:true})).toThrow();
 });
 it('only accepts this repository, TLS, exact x64 assets and bounded size',()=>{
   for(const url of ['http://github.com/a','https://evil.example/a','https://github.com/other/repo/releases/download/v1.0.1/'+name]){
     const value=metadata();value.assets[0].browser_download_url=url;expect(()=>releaseOffer('1.0.0',value)).toThrow();
   }
   const value=metadata();value.assets[0].name='other.exe';expect(()=>releaseOffer('1.0.0',value)).toThrow();
 });
 it('rejects malformed/duplicate/missing checksum records',()=>{
   for(const text of ['bad',`${hash}  ${name}\n${hash}  ${name}`,`${hash}  other.exe`])expect(()=>checksumFor(text,name)).toThrow();
 });
 it('downloads and actually verifies bytes before declaring ready',async()=>{
   const {manager,download}=await fixture();const ready=await manager.downloadUpdate('1.0.1');
   expect(ready.sha256).toBe(hash);expect(ready.ready).toBe(true);expect(download).toHaveBeenCalledTimes(2);
 });
 it('does not silently download another version after consent',async()=>{
   const {manager,download}=await fixture();await expect(manager.downloadUpdate('1.0.2')).rejects.toThrow('版本已变化');
   expect(download).not.toHaveBeenCalled();
 });
 it('network failure leaves no installable update',async()=>{
   const {manager}=await fixture({network:true});await expect(manager.downloadUpdate()).rejects.toThrow('network');
   await expect(manager.install(async()=>({}),async()=>{})).rejects.toThrow('先下载');
 });
 it('hash failure prevents prepare/launch',async()=>{
   const {manager}=await fixture({badHash:true});await expect(manager.downloadUpdate()).rejects.toThrow('SHA256');
   const prepare=vi.fn(),launch=vi.fn();await expect(manager.install(prepare,launch)).rejects.toThrow();
   expect(prepare).not.toHaveBeenCalled();expect(launch).not.toHaveBeenCalled();
 });
 it('checks for tampering again before backup or executable launch',async()=>{
   const {manager,root}=await fixture();await manager.downloadUpdate();const folders=await readdir(path.join(root,'updates'));
   await writeFile(path.join(root,'updates',folders[0],name),'modified');const prepare=vi.fn(),launch=vi.fn();
   await expect(manager.install(prepare,launch)).rejects.toThrow('发生改变');expect(prepare).not.toHaveBeenCalled();expect(launch).not.toHaveBeenCalled();
 });
 it('refuses installer launch if task protection/backup fails',async()=>{
   const {manager}=await fixture();await manager.downloadUpdate();const launch=vi.fn();
   await expect(manager.install(async()=>{throw new Error('backup failed');},launch)).rejects.toThrow('backup failed');expect(launch).not.toHaveBeenCalled();
 });
 it('retains metadata after install failure without claiming rollback',async()=>{
   const {manager,root}=await fixture();await manager.downloadUpdate();
   await expect(manager.install(async()=>({path:'owned-backup'}),async()=>{throw new Error('spawn failed');})).rejects.toThrow('spawn failed');
   expect(JSON.parse(await readFile(path.join(root,'pending-update.json'),'utf8')).backup.path).toBe('owned-backup');
   expect((await updateReceipt(root,'1.0.0'))?.verified).toBe(false);
 });
 it('pauses/backs up before launch, verifies only actual restarted version',async()=>{
   const {manager,root}=await fixture();await manager.downloadUpdate();const order:string[]=[];
   const result=await manager.install(async()=>{order.push('backup');return {path:'owned-backup'};},async()=>{order.push('launch');});
   expect(order).toEqual(['backup','launch']);expect(result.verified_installation).toBe(false);
   expect((await updateReceipt(root,'1.0.1'))?.verified).toBe(true);
 });
});
