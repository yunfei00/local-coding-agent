// Explicit local-only Windows acceptance. Use a dedicated data directory.
const fs=require('node:fs');
const path=require('node:path');
const crypto=require('node:crypto');
const {spawnSync}=require('node:child_process');
const port=Number(process.argv[2]||11434);
const model=process.argv[3]||'gemma4:31b';
if(process.platform!=='win32'||!Number.isInteger(port)||port<1||port>65535||!/^[a-zA-Z0-9][a-zA-Z0-9_.:/-]{0,127}$/.test(model))throw Error('Invalid Windows/local model configuration');
if(!process.env.LCA_DATA_DIR||!path.isAbsolute(process.env.LCA_DATA_DIR))throw Error('Set absolute LCA_DATA_DIR for the isolated acceptance');
const dataDir=path.resolve(process.env.LCA_DATA_DIR);
fs.mkdirSync(dataDir,{recursive:true});
const lease=path.join(fs.realpathSync(dataDir),'engine-execution.lock');
const token=process.pid+':'+crypto.randomBytes(16).toString('hex');
fs.mkdirSync(lease);
const owner=path.join(lease,'owner');
fs.writeFileSync(owner,token,{flag:'wx'});
const dir=fs.mkdtempSync(path.join(fs.realpathSync(dataDir),'p2-acceptance-'));
const report={model,port,rounds:[],result:'BLOCKED',processCleanupConfirmed:true};
let safe=true;
try{
  for(let round=1;round<=3;round++){
    safe=false;
    const result=spawnSync(process.execPath,[path.join(__dirname,'p0-model.cjs'),String(port),'--p2',model],{encoding:'utf8',windowsHide:true,env:{...process.env,LCA_P2_FIXTURE_ONLY:'1'},maxBuffer:8*1024*1024});
    fs.writeFileSync(path.join(dir,'round-'+round+'.json'),result.stdout||'');
    fs.writeFileSync(path.join(dir,'round-'+round+'.stderr.txt'),result.stderr||'');
    let childReport;
    try{childReport=JSON.parse(result.stdout);}catch{}
    safe=childReport?.processReaped===true && !result.error && result.signal===null;
    report.rounds.push({round,exitCode:result.status,result:childReport?.result??'BLOCKED',report:childReport?.report,processReaped:safe,cases:childReport?.cases?.map(({name,status,failure,modelRequests,events})=>({name,status,failure,modelRequests,events}))});
    if(!safe||childReport.result==='BLOCKED')break;
  }
  report.result=report.rounds.length===3&&report.rounds.every(r=>r.exitCode===0&&r.result==='PASS')?'PASS':'PARTIAL';
}catch(error){report.error=String(error);report.result='BLOCKED';}
finally{
  report.processCleanupConfirmed=safe;
  if(!safe)report.result='BLOCKED';
  if(safe && fs.readFileSync(owner,'utf8')===token){fs.unlinkSync(owner);fs.rmdirSync(lease);}
  else report.leaseRetained=true;
  fs.writeFileSync(path.join(dir,'summary.json'),JSON.stringify(report,null,2));
  console.log(JSON.stringify({report:path.join(dir,'summary.json'),...report},null,2));
  process.exitCode=report.result==='PASS'?0:1;
}
