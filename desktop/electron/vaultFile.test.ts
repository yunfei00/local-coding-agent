import {it,expect,vi} from 'vitest';
import {mkdtempSync,writeFileSync,readFileSync,rmSync,mkdirSync,readdirSync} from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {readProtectedJSON,writeProtectedCipher} from './vaultFile';

it('atomically replaces encrypted vault and preserves a destination on commit failure',()=>{
 const root=mkdtempSync(path.join(os.tmpdir(),'lca-vault-write-'));
 try{
  const file=path.join(root,'vault.json');writeFileSync(file,'old-encrypted');
  writeProtectedCipher(file,'new-encrypted');expect(JSON.parse(readFileSync(file,'utf8'))).toEqual({encrypted:'new-encrypted'});
  const blocked=path.join(root,'blocked');mkdirSync(blocked);writeFileSync(path.join(blocked,'preserved'),'retain');
  expect(()=>writeProtectedCipher(blocked,'not-committed')).toThrow('未覆盖');
  expect(readFileSync(path.join(blocked,'preserved'),'utf8')).toBe('retain');
  expect(readdirSync(root).some(name=>name.endsWith('.pending'))).toBe(false);
 }finally{rmSync(root,{recursive:true,force:true});}
});

it('validates flat and MCP credential maps through the OS decrypt adapter',()=>{
 const root=mkdtempSync(path.join(os.tmpdir(),'lca-vault-test-'));const file=path.join(root,'vault.json');
 try{
  writeFileSync(file,JSON.stringify({encrypted:'eA=='}));
  expect(readProtectedJSON(file,()=>JSON.stringify({reference:'fixture-value'}),'flat')).toEqual({reference:'fixture-value'});
  expect(readProtectedJSON(file,()=>JSON.stringify({server:{ENV:'fixture-value'}}),'nested')).toEqual({server:{ENV:'fixture-value'}});
  expect(()=>readProtectedJSON(file,()=>JSON.stringify([]),'flat')).toThrow('原文件保留');
 }finally{rmSync(root,{recursive:true,force:true});}
});
it('corruption never exposes contents in errors or replaces the original',()=>{
 const root=mkdtempSync(path.join(os.tmpdir(),'lca-vault-test-'));const file=path.join(root,'vault.json');
 try{
  const original='sensitive-invalid-json-value';writeFileSync(file,original);const decrypt=vi.fn();
  try{readProtectedJSON(file,decrypt,'flat');throw new Error('expected failure');}catch(error){expect(String(error)).not.toContain(original);}
  expect(readFileSync(file,'utf8')).toBe(original);expect(decrypt).not.toHaveBeenCalled();
 }finally{rmSync(root,{recursive:true,force:true});}
});
it('oversized vault is rejected before decryption',()=>{
 const root=mkdtempSync(path.join(os.tmpdir(),'lca-vault-test-'));const file=path.join(root,'vault.json');
 try{writeFileSync(file,Buffer.alloc(16*1024*1024+1));const decrypt=vi.fn();expect(()=>readProtectedJSON(file,decrypt,'flat')).toThrow();expect(decrypt).not.toHaveBeenCalled();}
 finally{rmSync(root,{recursive:true,force:true});}
});
