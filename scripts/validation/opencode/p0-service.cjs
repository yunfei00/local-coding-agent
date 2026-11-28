// Fixed-version Windows P0. No model credentials or model requests.
const fs = require('node:fs');
const path = require('node:path');
const cp = require('node:child_process');
const crypto = require('node:crypto');
const lock = require('./version-lock.json');
const root = path.resolve('build/opencode-p0');
const binary = path.join(root,'verified-bin/opencode.exe');
if (crypto.createHash('sha256').update(fs.readFileSync(binary)).digest('hex') !== lock.executable_sha256)
  throw Error('Fixed-version executable hash mismatch');
const run = path.join(root, 'service-' + crypto.randomUUID());
fs.mkdirSync(run, {recursive:true});
const password = crypto.randomBytes(32).toString('hex');
const env = Object.fromEntries(Object.entries(process.env).filter(([k]) =>
  !/key|token|secret|credential|password/i.test(k)));
Object.assign(env, {
  OPENCODE_TEST_HOME:run, OPENCODE_CONFIG_DIR:path.join(run,'config'),
  XDG_CONFIG_HOME:path.join(run,'config'), XDG_DATA_HOME:path.join(run,'data'),
  XDG_CACHE_HOME:path.join(run,'cache'), XDG_STATE_HOME:path.join(run,'state'),
  OPENCODE_PASSWORD:password, OPENCODE_DISABLE_MODELS_FETCH:'1',
  OPENCODE_DISABLE_PROJECT_CONFIG:'1', OPENCODE_DISABLE_CLAUDE_CODE:'1',
  OPENCODE_CONFIG_CONTENT:JSON.stringify({provider:{},enabled_providers:[]})
});
const report = {version:lock.version,model_requests:0,steps:[],run};
const child=cp.spawn(binary,
  ['serve','--hostname','127.0.0.1','--port','0'], {cwd:run,env,windowsHide:true});
let text='';
let spawnError;
child.on('error',error=>{spawnError=error;});
child.stdout.on('data',b=>text=(text+b).slice(-4000));
child.stderr.resume();
(async()=>{
  try {
    const deadline=Date.now()+60000;
    while(!text.match(/http:\/\/127\.0\.0\.1:\d+/) && Date.now()<deadline && child.exitCode===null && !spawnError)
      await new Promise(r=>setTimeout(r,100));
    const url=text.match(/http:\/\/127\.0\.0\.1:\d+/)?.[0];
    if(!url) throw Error('Service readiness failed; exit='+child.exitCode);
    const headers={authorization:'Basic '+Buffer.from('opencode:'+password).toString('base64')};
    const call=(route, options={})=>fetch(url+route,{...options,
      headers:{...headers,'content-type':'application/json',...options.headers},signal:AbortSignal.timeout(8000)});
    const unauth=await fetch(url+'/api/info',{signal:AbortSignal.timeout(8000)});
    report.steps.push({name:'unauthenticated',status:unauth.status});
    if(unauth.status!==401) throw Error('Unauthenticated API was not denied');
    const info=await call('/api/info');
    const body=await info.json();
    if(info.status!==200||!String(body.version).includes('2.2.6'))throw Error('Version/health mismatch');
    report.steps.push({name:'health',status:info.status,version:body.version});
    const spec=await call('/openapi.json');
    fs.writeFileSync(path.join(run,'openapi.json'),JSON.stringify(await spec.json(),null,2));
    const create=await call('/api/session',{method:'POST',body:JSON.stringify({title:'P0 isolated no-model session',
      permissions:[{action:'*',resource:'*',effect:'deny'}]})});
    const session=await create.json();
    report.steps.push({name:'create',status:create.status});
    if(create.status!==200) throw Error('Session create rejected');
    report.session_id=session.data?.id;
    if(!report.session_id) throw Error('Missing created session ID');
    const list=await call('/api/session');
    const listed=JSON.stringify(await list.json());
    if(list.status!==200||!listed.includes(report.session_id))throw Error('Created session not found on re-query');
    report.steps.push({name:'reconnect-list',status:list.status});
    const interrupted=await call('/api/session/'+report.session_id+'/interrupt',{method:'POST'});
    const idle=await interrupted.json();
    if(interrupted.status!==200||idle.interrupted!==false)throw Error('Idle interrupt mismatch');
    report.steps.push({name:'idle-interrupt',status:interrupted.status,interrupted:idle.interrupted});
    const controller=new AbortController();
    const stream=await fetch(url+'/api/event',{headers,signal:controller.signal});
    if(stream.status!==200)throw Error('Event stream unavailable');
    const reader=stream.body.getReader();
    const first=await Promise.race([reader.read(), new Promise((_,reject)=>setTimeout(()=>reject(Error('SSE timeout')),5000))]);
    if(!first.value?.byteLength)throw Error('Empty event stream');
    report.steps.push({name:'event-stream',status:stream.status,received_bytes:first.value?.byteLength||0});
    controller.abort();
    report.result='PARTIAL';
  } catch(e) {
    report.result='BLOCKED';
    report.error=String(e.message).replaceAll(password,'[redacted]');
  } finally {
    if(child.pid && child.exitCode===null) {
      if(process.platform==='win32')cp.spawnSync('taskkill',['/PID',String(child.pid),'/T','/F'],{windowsHide:true,stdio:'ignore'});
      else child.kill('SIGTERM');
      await Promise.race([new Promise(resolve=>child.exitCode!==null?resolve():child.once('exit',resolve)),
        new Promise(resolve=>setTimeout(resolve,5000))]);
    }
    report.exit_code=child.exitCode;
    report.process_reaped=child.exitCode!==null||!child.pid;
    if(!report.process_reaped)report.result='BLOCKED';
    fs.writeFileSync(path.join(run,'report.json'),JSON.stringify(report,null,2));
    console.log(JSON.stringify(report,null,2));
    process.exitCode=report.result==='BLOCKED'?1:0;
  }
})();
