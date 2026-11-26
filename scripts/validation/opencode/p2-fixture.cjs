// Trusted fixture and independent assertions. No model-supplied commands are executed here.
const fs=require('node:fs');
const path=require('node:path');
const {spawnSync}=require('node:child_process');
const assert=require('node:assert/strict');
const crypto=require('node:crypto');
const os=require('node:os');
const deny={action:'*',resource:'*',effect:'deny'};
const allow=(action,resource)=>({action,resource,effect:'allow'});
const original='module.exports = (a, b) => a - b;\n';
const repaired='module.exports = (a, b) => a + b;\n';
const testSource="const assert = require('node:assert/strict');\nconst add = require('./add.cjs');\nassert.equal(add(7, 8), 15);\nassert.equal(add(-3, 2), -1);\nassert.equal(add(0, 0), 0);\n";
function read(root,name){
  const file=path.join(root,name);
  const stat=fs.lstatSync(file);
  assert(stat.isFile()&&!stat.isSymbolicLink()&&stat.size<=65536,'Unsafe fixture file');
  assert.equal(path.dirname(fs.realpathSync(file)),fs.realpathSync(root));
  return fs.readFileSync(file,'utf8').replace(/\r\n/g,'\n');
}
function run(exe,args,root){
  const env=Object.fromEntries(Object.entries(process.env).filter(([k])=>!/^GIT_|^NODE_OPTIONS$|^NODE_PATH$/i.test(k)));
  Object.assign(env,{GIT_CONFIG_NOSYSTEM:'1',GIT_CONFIG_GLOBAL:process.platform==='win32'?'NUL':'/dev/null',GIT_TERMINAL_PROMPT:'0'});
  const result=spawnSync(exe,args,{cwd:root,env,encoding:'utf8',timeout:15000,windowsHide:true,shell:false});
  if(result.error)throw result.error;
  return {exitCode:result.status,stdout:result.stdout,stderr:result.stderr};
}
function init(root){
  const marker='P2-'+crypto.randomBytes(6).toString('hex');
  fs.writeFileSync(path.join(root,'seed.txt'),marker,{flag:'wx'});
  fs.writeFileSync(path.join(root,'add.cjs'),original,{flag:'wx'});
  fs.writeFileSync(path.join(root,'test-add.cjs'),testSource,{flag:'wx'});
  // Only in the freshly generated fixture, never an existing user's worktree.
  for(const args of [['init','--quiet','--template='],['-c','core.autocrlf=false','add','--','seed.txt','add.cjs','test-add.cjs']]){
    assert.equal(run('git',args,root).exitCode,0,'Git fixture setup failed');
  }
  return marker;
}
function verifyRepair(root){
  try{
    assert.equal(read(root,'add.cjs'),repaired);
    assert.equal(read(root,'test-add.cjs'),testSource);
    // Execute a trusted copy, not a mutable file that the model can replace.
    const isolated=fs.mkdtempSync(path.join(os.tmpdir(),'lca-p2-verify-'));
    try{
      fs.writeFileSync(path.join(isolated,'add.cjs'),repaired,{flag:'wx'});
      fs.writeFileSync(path.join(isolated,'test-add.cjs'),testSource,{flag:'wx'});
      const result=run(process.execPath,['test-add.cjs'],isolated);
      assert.equal(result.exitCode,0);
    }finally{fs.rmSync(isolated,{recursive:true,force:true});}
    return true;
  }catch{return false;}
}
function verifyTree(root,marker){
  try{
    assert.equal(read(root,'seed.txt'),marker);
    assert.equal(read(root,'result.txt').trim(),marker+'-VERIFIED');
    assert.equal(read(root,'test-add.cjs'),testSource);
    assert.deepEqual(fs.readdirSync(root).sort(),['.git','add.cjs','result.txt','seed.txt','test-add.cjs']);
    return verifyRepair(root);
  }catch{return false;}
}
async function runP2Cases(api,root,runCase){
  const marker=init(root);
  const succeeded=(events,n)=>events.filter(e=>e.type==='session.tool.success').length>=n;
  await runCase(api,'p2_read','Read seed.txt using the read tool and report exactly its content.',[deny,allow('read','seed.txt')],(answer,tools)=>succeeded(tools,1)&&answer.includes(marker));
  await runCase(api,'p2_create','Read seed.txt. Create result.txt containing its exact contents followed by -VERIFIED. Use only file tools.',[deny,allow('read','seed.txt'),allow('edit','result.txt')],(_,tools)=>succeeded(tools,2)&&read(root,'result.txt').trim()===marker+'-VERIFIED'&&read(root,'seed.txt')===marker);
  await runCase(api,'p2_repair','Read add.cjs and fix the subtraction bug so it exports addition. Keep the exact one-line format and do not touch test-add.cjs. Use file tools only.',[deny,allow('read','add.cjs'),allow('edit','add.cjs')],(_,tools)=>succeeded(tools,2)&&verifyRepair(root));
  await runCase(api,'p2_shell','Use the shell to run exactly: echo P2_SHELL_CHECK\nReport its output.',[deny,allow('shell','echo P2_SHELL_CHECK')],(answer,tools)=>succeeded(tools,1)&&answer.includes('P2_SHELL_CHECK'));
  await runCase(api,'p2_git_status','Use the shell to run exactly: git status --short\nReport the status of add.cjs.',[deny,allow('shell','git status --short')],(answer,tools)=>succeeded(tools,1)&&answer.includes('add.cjs'));
  await runCase(api,'p2_git_diff','Use the shell to run exactly: git diff -- add.cjs\nReport the addition change.',[deny,allow('shell','git diff -- add.cjs')],(answer,tools)=>succeeded(tools,1)&&answer.includes('add.cjs'));
  const first=await runCase(api,'p2_context_store','Remember this identifier for the next message: '+marker+'. Reply READY only. Do not use tools.',[deny],(answer,tools)=>answer.includes('READY')&&tools.length===0);
  if(first.status==='PASS'){
    // Wait for the session drain to end. Do not re-submit on disconnect.
    let idle=false;
    for(let i=0;i<30;i++){
      const response=await api('/api/session/active');
      if(response.ok && !(first.sessionId in (await response.json()).data)){idle=true;break;}
      await new Promise(resolve=>setTimeout(resolve,100));
    }
    if(idle)await runCase(api,'p2_context_recall','What was the identifier in my preceding message? Reply only with that identifier.',[deny],(answer,tools)=>answer.includes(marker)&&tools.length===0,{sessionId:first.sessionId});
  }
  return verifyTree(root,marker);
}
module.exports={runP2Cases,verifyRepair,verifyTree,init,original,repaired,testSource};
