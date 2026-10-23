const fs=require('node:fs');
const path=require('node:path');
const runtime=path.resolve(__dirname,'.runtime');
if(path.dirname(runtime)!==path.resolve(__dirname)) throw new Error('Unsafe cleanup target');
if(fs.existsSync(path.join(runtime,'process.json'))){
  const {pid}=JSON.parse(fs.readFileSync(path.join(runtime,'process.json'),'utf8'));
  try {process.kill(pid,0);throw new Error('Close the controlled Electron window before cleanup');}
  catch(error){if(error.code!=='ESRCH') throw error;}
}
fs.rmSync(runtime,{recursive:true,force:true});
console.log('Removed only this fixture runtime; source and dependencies retained.');
