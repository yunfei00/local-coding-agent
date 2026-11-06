import {readFileSync,statSync,openSync,writeFileSync,fsyncSync,closeSync,renameSync,unlinkSync} from 'node:fs';
import {randomUUID} from 'node:crypto';

/** Encrypt before calling; never truncate the last readable vault in place. */
export function writeProtectedCipher(file:string,encrypted:string,field='encrypted'):void {
  const temporary=file+'.'+randomUUID()+'.pending';let descriptor:number|undefined;
  try{
    descriptor=openSync(temporary,'wx',0o600);
    writeFileSync(descriptor,JSON.stringify({[field]:encrypted}),'utf8');fsyncSync(descriptor);
    closeSync(descriptor);descriptor=undefined;renameSync(temporary,file);
  }catch{
    if(descriptor!==undefined)closeSync(descriptor);
    try{unlinkSync(temporary);}catch{/* Original vault is preserved. */}
    throw new Error('加密凭据保存失败，未覆盖原文件；请检查磁盘与目录权限。');
  }
}

/** Reads only; failure never rewrites or logs encrypted/plain credential bytes. */
export function readProtectedJSON<T>(file:string,decrypt:(cipher:Buffer)=>string,shape:'flat'|'nested'):T {
  try{
    if(statSync(file).size>16*1024*1024)throw new Error('size');
    const outer=JSON.parse(readFileSync(file,'utf8'));
    if(typeof outer.encrypted!=='string'||!outer.encrypted)throw new Error('format');
    const values=JSON.parse(decrypt(Buffer.from(outer.encrypted,'base64')));
    const object=(value:unknown):value is Record<string,unknown>=>!!value&&typeof value==='object'&&!Array.isArray(value);
    if(!object(values)||Object.values(values).some(value=>shape==='flat'?typeof value!=='string':!object(value)||Object.values(value).some(item=>typeof item!=='string')))throw new Error('shape');
    return values as T;
  }catch{throw new Error('加密凭据库无法读取，原文件保留；请检查 OS 安全存储或从备份恢复。');}
}
