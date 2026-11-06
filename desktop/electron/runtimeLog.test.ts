import {it,expect} from 'vitest';
import {mkdtempSync,readFileSync,readdirSync,rmSync,statSync} from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {appendBoundedLog} from './runtimeLog';

it('redacts credentials, rotates bounded logs and refuses path escapes',()=>{
 const root=mkdtempSync(path.join(os.tmpdir(),'lca-log-test-'));
 try{
   for(let n=0;n<40;n++)appendBoundedLog(root,'desktop.log','provider secret-value-987 Authorization: Bearer sensitive-token '+('x'.repeat(100)),['secret-value-987'],512);
   const names=readdirSync(root);expect(names.length).toBeLessThanOrEqual(4);
   for(const name of names){const text=readFileSync(path.join(root,name),'utf8');expect(text).not.toContain('secret-value-987');expect(text).not.toContain('sensitive-token');expect(statSync(path.join(root,name)).size).toBeLessThanOrEqual(512);}
   expect(()=>appendBoundedLog(root,'../outside.log','text')).toThrow();
 }finally{rmSync(root,{recursive:true,force:true});}
});
