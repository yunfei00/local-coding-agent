import {appendFileSync,existsSync,mkdirSync,renameSync,statSync,unlinkSync} from 'node:fs';
import path from 'node:path';

export function appendBoundedLog(directory:string,name:string,message:string,secrets:string[]=[],limit=2*1024*1024){
  if(path.basename(name)!==name||!/^[a-z0-9.-]+\.log$/i.test(name))throw new Error('Invalid log name');
  let safe=String(message);
  for(const secret of secrets)if(secret.length>=4)safe=safe.split(secret).join('[REDACTED]');
  safe=safe.replace(/\b(?:sk-[\w-]{16,}|gh[pousr]_[\w]{20,})\b/g,'[REDACTED]')
    .replace(/(authorization\s*[:=]\s*(?:bearer\s+)?)[^\s,;]+/gi,'$1[REDACTED]')
    .replace(/((?:api[_-]?key|password|cookie)\s*[:=]\s*)[^\s,;]+/gi,'$1[REDACTED]');
  const line=new Date().toISOString()+' '+Buffer.from(safe).subarray(0,60000).toString('utf8')+'\n';
  mkdirSync(directory,{recursive:true});const file=path.join(directory,name);
  if(existsSync(file)&&statSync(file).size+Buffer.byteLength(line)>limit){
    const oldest=file+'.3';if(existsSync(oldest))unlinkSync(oldest);
    for(let n=2;n>=1;n--)if(existsSync(file+'.'+n))renameSync(file+'.'+n,file+'.'+(n+1));
    renameSync(file,file+'.1');
  }
  appendFileSync(file,line,'utf8');
}
