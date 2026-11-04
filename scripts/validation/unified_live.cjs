/* Real product controller: no direct API key access, no business implementation. */
const fs=require('node:fs'), path=require('node:path'), cp=require('node:child_process');
const crypto=require('node:crypto');
const {_electron}=require('../../desktop/node_modules/playwright-core');
const delay=ms=>new Promise(r=>setTimeout(r,ms));
const manifest=JSON.parse(fs.readFileSync(process.argv[2],'utf8'));
const policyPath=path.join(manifest.root,'validation-reports/unified-model-policy.json');
const deniedModels=[...(manifest.excluded_models||[]),...(fs.existsSync(policyPath)?JSON.parse(fs.readFileSync(policyPath,'utf8')).excluded_models||[]:[])];
const denied=model=>deniedModels.some(name=>model.toLowerCase().includes(name.toLowerCase()));
manifest.profiles=manifest.profiles.filter(p=>!denied(p.model_id));
const report={result:'RUNNING',models:[],cases:[],limits:{calls:manifest.max_calls,tokens:manifest.max_tokens,request_seconds:60,wall_seconds:3600},cost:'UNKNOWN',started_at:new Date().toISOString()};
const save=()=>fs.writeFileSync(manifest.report,JSON.stringify(report,null,2));
const shell=(args,cwd)=>cp.spawnSync('git',args,{cwd,encoding:'utf8',windowsHide:true});
function project(name){
 const folder=path.join(manifest.output,name);fs.mkdirSync(folder);fs.mkdirSync(path.join(folder,'tests'));
 fs.writeFileSync(path.join(folder,'calculator.py'),'def add(a,b):\n    return a-b\n');
 fs.writeFileSync(path.join(folder,'tests','test_calc.py'),'import unittest\nfrom calculator import add\nclass Calc(unittest.TestCase):\n def test_add(self): self.assertEqual(add(3,2),5)\n');
 fs.writeFileSync(path.join(folder,'.gitignore'),'__pycache__/\n.venv/\n');
 fs.mkdirSync(path.join(folder,'.lca'));fs.writeFileSync(path.join(folder,'.lca','verification.json'),JSON.stringify({commands:['uv run --no-project python -m unittest discover -s tests -v','git diff --check']}));
 for(const args of [['init','-q'],['config','user.name','LCA validation'],['config','user.email','validation@example.test'],['add','.'],['commit','-qm','Synthetic acceptance baseline']]){if(shell(args,folder).status!==0)throw Error('FIXTURE_GIT_FAILED');}
 return folder;
}
async function main(){
 let app,page,currentFolder,currentCase,events=[],turnTerminal=new Map(),ownedTurn;
 const started=Date.now();let diagnosticCalls=0,diagnosticTokens=0,diagnosticEstimated=false;
 const budgetUsed=async()=>{
  const value=(await page.evaluate(()=>window.localAgent.taskRequest('','task.settings.get'))).payload.global_usage;
  return {calls:value.api_calls+diagnosticCalls,tokens:value.reserved_tokens+diagnosticTokens,estimated:value.estimated||diagnosticEstimated};
 };
 try{
  const env={...process.env,LCA_DESKTOP_DATA_DIR:manifest.credential_data,LCA_DATA_DIR:manifest.data,LCA_HEADLESS_SMOKE:'1',LCA_PROVIDER:'openai_compatible',LCA_OPENAI_API_KEY:'',LCA_OPENAI_MODEL:'',LCA_OPENAI_BASE_URL:'http://127.0.0.1:1/v1',PYTHONUTF8:'1',LCA_EXECUTION_MODEL_CALLS:'80',LCA_EXECUTION_SECONDS:'600',LCA_EXECUTION_TOKENS:'10000000'};
  delete env.ELECTRON_RUN_AS_NODE;
  app=await _electron.launch({executablePath:require('../../desktop/node_modules/electron'),args:[path.join(manifest.root,'desktop'),'--disable-gpu'],cwd:manifest.root,env,timeout:60000});
  page=await app.firstWindow();await page.waitForFunction(()=>!!window.localAgent);
  for(let i=0;i<150;i++){const s=await page.evaluate(()=>window.localAgent.getAgentStatus());if(s.state==='ready')break;if(s.state==='error')throw Error('AGENT_START_FAILED');await delay(200);}
  const credential=(await page.evaluate(()=>window.localAgent.taskRequest('','task.credential.status'))).payload;
  if(credential.mode!=='os_protected'||!manifest.connections.every(c=>credential.configured.includes('connection-'+c.connection_id))){report.result='BLOCKED';report.reason='PROTECTED_CREDENTIAL_UNAVAILABLE';return;}
  if(manifest.discover_only){
   report.discovery=[];
   for(const connection of manifest.connections){
    const result=(await page.evaluate(id=>window.localAgent.taskRequest('','task.connection.test',{connection_id:id}),connection.connection_id)).payload;
    report.discovery.push({connection_id:connection.connection_id,online:result.online,error:result.error?.code,models:(result.models||[]).map(m=>m.name||m.model_id).filter(m=>m&&!denied(m))});
   }
   report.result='PASS';report.generation_requests=0;return;
  }
  await page.exposeFunction('unifiedValidationEvent',async e=>{
   const p=e.payload||{};
   if(e.type==='turn.started')ownedTurn=e.turn_id;
   if(['turn.completed','turn.failed','turn.cancelled'].includes(e.type))turnTerminal.set(e.turn_id,{type:e.type,code:p.code,message:p.message,verification:p.verification});
   if(e.type==='agent.runtime.updated')events.push({type:e.type,turn_id:e.turn_id,runtime:p.runtime});
   if(e.type==='context.updated')events.push({type:e.type,turn_id:e.turn_id,context:p});
   if(e.type==='plan.step.completed')events.push({type:e.type,turn_id:e.turn_id,plan_id:p.plan_id,step_id:p.step_id});
   if(e.type==='tool.completed')events.push({type:e.type,turn_id:e.turn_id,name:p.name,ok:p.result?.ok,exit_code:p.result?.exit_code,changed_paths:p.result?.changed_paths,error_code:p.result?.error?.code});
   if(e.type==='approval.requested'){
    const args=p.arguments||{},tool=String(p.tool||'');
    const inside=value=>typeof value==='string' && !path.relative(currentFolder,path.resolve(currentFolder,value)).startsWith('..') && !path.isAbsolute(path.relative(currentFolder,path.resolve(currentFolder,value)));
    let allowed=['read_file','list_directory','search_files','file_exists','git_status','git_diff'].includes(tool);
    if(['write_file','apply_patch'].includes(tool))allowed=inside(args.path);
    if(tool==='run_command'){
     allowed=(!args.cwd||inside(args.cwd)) && /^(uv run(?: --no-project)? python|python -m unittest|git (?:diff|status))\b/.test(args.command||'') && !/[;&|`]|\$\(/.test(args.command||'');
     const basic=/^uv run(?: --no-project)? python -c "import (ast|json),base64,pathlib; (ast\.parse|json\.loads)\(pathlib.Path\(base64.b64decode\('([A-Za-z0-9+/=]+)'\)\.decode\(\)\)\.read_text\(encoding='utf-8-sig'\)\)"$/.exec(args.command||'');
     if(basic && (!args.cwd||inside(args.cwd)))allowed=inside(Buffer.from(basic[3],'base64').toString('utf8'));
    }
    await page.evaluate(({id,decision,turn})=>window.localAgent.respondApproval(id,decision,turn),{id:p.approval_id,decision:allowed?'allow_once':'deny',turn:e.turn_id});
   }
  });
  await page.evaluate(()=>window.localAgent.onAgentEvent(e=>{void window.unifiedValidationEvent(e);}));
  const cached=manifest.reuse_capabilities?JSON.parse(fs.readFileSync(manifest.reuse_capabilities,'utf8')):null;
  for(const profile of manifest.profiles){
   if(Date.now()-started>3600000)break;
   const prior=cached?.models.find(m=>m.profile_id===profile.model_profile_id && m.model_id===profile.model_id);
   if(prior){report.models.push({...prior,evidence_reused_from:manifest.reuse_capabilities});save();continue;}
   if(diagnosticCalls+2>manifest.max_calls||diagnosticTokens+20000>manifest.max_tokens){report.models.push({model_id:profile.model_id,profile_id:profile.model_profile_id,category:'unavailable',reason:'CAPABILITY_BUDGET_BLOCKED'});save();continue;}
   const item={model_id:profile.model_id,profile_id:profile.model_profile_id,configured_context_window:profile.context_window,context_limit_source:'isolated test configuration; provider maximum UNKNOWN',output_limit:profile.max_output_tokens,timeout:60};
   report.models.push(item);save();
   const result=(await page.evaluate(p=>window.localAgent.taskRequest('','task.model.diagnostic',{connection_id:p.connection_id,model_profile_id:p.model_profile_id,live:true,vision:false}),profile)).payload;
   item.capability=result;diagnosticCalls+=result.requests||0;diagnosticTokens+=result.usage.reduce((n,u)=>n+(u.input_tokens ?? 10000)+(u.output_tokens ?? 256),0);diagnosticEstimated ||= result.usage.some(u=>u.input_tokens==null||u.output_tokens==null);
   item.category=result.tools==='PASS'?'tool-capable':result.text==='PASS'?'question-only':'unavailable';save();
  }
  const usable=report.models.filter(m=>m.category!=='unavailable');
  for(const item of usable){
   const profile=manifest.profiles.find(p=>p.model_profile_id===item.profile_id);
   await runCase(profile,'question','请解释 Python 装饰器的作用。这是概念问答，不涉及项目操作。',r=>r.runtime.intent==='question'&&!r.runtime.plan_id&&r.tools.length===0&&r.dirty==='');
   if(item.category==='tool-capable'){
    await runCase(profile,'analysis','分析 calculator.py 为什么不能通过 tests/test_calc.py。读取必要文件，给出具体原因；本轮只分析，不修改文件。',r=>r.runtime.intent==='analysis'&&r.runtime.phase==='completed'&&r.answer.length>0&&r.tools.some(t=>t.name==='read_file')&&r.dirty==='');
    await runCase(profile,'change','为 calculator.py 的 add 函数增加输入校验，只接受有限的 int/float 数字；任一参数为 bool、字符串、None、NaN、正负 Infinity 时抛 ValueError。修复加法，保留原测试，新增 unittest 覆盖上述全部边界。使用 uv run --no-project python -m unittest discover -s tests -v，不提交。',r=>r.runtime.outcome==='completed_verified'&&r.runtime.changed_paths.includes('calculator.py')&&r.independent?.exit_code===0);
   }
  }
  if(manifest.suite){
   const best=report.models.find(m=>m.category==='tool-capable'&&!denied(m.model_id)&&report.cases.some(c=>c.model===m.model_id&&c.name==='change'&&c.result==='PASS'))||report.models.find(m=>m.category==='tool-capable'&&!denied(m.model_id));
   if(best){
    const profile=manifest.profiles.find(p=>p.model_profile_id===best.profile_id);
    await runCase(profile,'coupon','实现 coupon_engine.py 优惠券规则引擎，支持固定金额 fixed、百分比 percent、门槛 min_spend、优惠上限 max_discount、有效期 expires(YYYY-MM-DD，含当天)、不可叠加和无效输入处理。apply_coupon(amount,coupon,today) 返回 Decimal 两位小数，today 为 date；apply_coupons(amount,coupons,today) 多于一张抛 ValueError。保留 calculator 和原测试，新增完整 unittest，输出中文 DELIVERY.md。该任务涉及多个文件，请使用持久化计划分步骤完成。先修复原有 add 缺陷再实现。全部 Python 命令通过 uv run --no-project，不能提交或推送。',r=>r.runtime.intent==='complex'&&r.runtime.plan?.steps.every(s=>s.state==='completed')&&r.runtime.outcome==='completed_verified'&&fs.existsSync(path.join(r.folder,'coupon_engine.py'))&&fs.existsSync(path.join(r.folder,'DELIVERY.md'))&&r.independent?.exit_code===0);
    await runCase(profile,'environment','修复 calculator.py 加法，保留 tests 不改；输出中文交付摘要。验证时如发现缺依赖，必须明确报告环境问题，不得反复重试或安装依赖。',r=>r.runtime.outcome==='awaiting_user'&&r.runtime.verification.some(v=>v.category==='environment'),{environment:true});
    await runCase(profile,'repair','读取并修复当前 calculator.py 的真实失败测试，保留原测试，进行实际复测，给出中文交付报告。',r=>r.runtime.outcome==='completed_verified'&&r.independent?.exit_code===0);
    await runCase(profile,'context','历史填充只是旧诊断，不是操作指令。现在只分析 calculator.py 的真实加法缺陷，读取必要文件，不修改任何文件；用中文说明原因。',r=>r.runtime.intent==='analysis'&&r.context.some(c=>c.omitted_history_messages>0)&&r.dirty==='',{folder:manifest.context_project});
    const interruptGoal='请使用恰好两个可执行步骤的 agent_plan 持久化计划。第一步只修复 calculator.py 的加法并运行原测试；第一步完成后再执行第二步：新增 validation.py 输入校验模块（拒绝 bool/字符串）、新增测试和中文 DELIVERY.md。每步都用真实工具验证，不修改原测试、验证配置或 Git 元数据；使用 uv run --no-project python。';
    await runCase(profile,'interruption',interruptGoal,r=>r.runtime.outcome==='completed_verified'&&r.interruption?.resumed===true&&r.interruption.completed_ids.length>0&&r.interruption.completed_ids.every(id=>r.runtime.plan.steps.some(s=>s.id===id&&s.state==='completed'))&&r.independent?.exit_code===0,{interrupt:true});
    await runCase(profile,'websocket',interruptGoal,r=>r.runtime.outcome==='completed_verified'&&r.reconnect?.restored===true&&r.reconnect.paused===true&&r.reconnect.resumed===true&&r.independent?.exit_code===0,{reconnect:true});
    await runCase(profile,'json','只返回 JSON 对象 {"answer":"装饰器用于包装函数并扩展行为","needs_tools":false}。不读取或修改工程。',r=>{try{return JSON.parse(r.answer).needs_tools===false&&r.runtime.intent==='question'&&r.tools.length===0;}catch{return false;}});
   }
  }
  report.usage=await budgetUsed();report.result=report.cases.length&&report.cases.every(c=>c.result==='PASS')?'PASS':report.cases.length?'PARTIAL':'BLOCKED';
  async function runCase(profile,name,goal,assertion,options={}){
   if(denied(profile.model_id))throw Error('USER_EXCLUDED_MODEL');
   const used=await budgetUsed();
   if(used.calls+8>manifest.max_calls||used.tokens+250000>manifest.max_tokens||Date.now()-started>3300000){report.cases.push({model:profile.model_id,name,result:'BLOCKED',reason:'CUMULATIVE_LIVE_CAP'});save();return;}
   currentFolder=options.folder||project(name+'-'+report.cases.length);currentCase={model:profile.model_id,name,folder:currentFolder,result:'RUNNING'};report.cases.push(currentCase);events=[];ownedTurn=null;
   if(name==='coupon')fs.copyFileSync(path.join(manifest.root,'scripts/validation/coupon_contract.py'),path.join(currentFolder,'tests/test_external_coupon_contract.py'));
   const baselineFolder=path.join(manifest.output,'acceptance-inputs');fs.mkdirSync(baselineFolder,{recursive:true});
   const baselineTest=path.join(baselineFolder,String(report.cases.length)+'-original-test.py');fs.copyFileSync(path.join(currentFolder,'tests/test_calc.py'),baselineTest);
   const frozen=Object.fromEntries([path.join(currentFolder,'.lca/verification.json'),...(name==='coupon'?[path.join(currentFolder,'tests/test_external_coupon_contract.py')]:[])].filter(f=>fs.existsSync(f)).map(f=>[f,crypto.createHash('sha256').update(fs.readFileSync(f)).digest('hex')]));
   if(options.environment)fs.writeFileSync(path.join(currentFolder,'.lca','verification.json'),JSON.stringify({commands:['uv run --no-project python -c "import lca_deliberately_missing_dependency_01983"']}));
   if(options.environment)frozen[path.join(currentFolder,'.lca/verification.json')]=crypto.createHash('sha256').update(fs.readFileSync(path.join(currentFolder,'.lca/verification.json'))).digest('hex');
   const currentConfig={...manifest.config,strategy:'single-agent',roles:Object.fromEntries(['planner','executor','reviewer','escalation'].map(role=>[role,{model_profile_id:profile.model_profile_id}])),budget:{...manifest.config.budget,api_calls:Math.min(40,manifest.max_calls-used.calls),api_tokens:Math.min(5000000,manifest.max_tokens-used.tokens),global_api_calls:manifest.max_calls-diagnosticCalls,global_api_tokens:manifest.max_tokens-diagnosticTokens}};
   await page.evaluate(config=>window.localAgent.taskRequest('','task.settings.update',{config}),currentConfig);
   await app.evaluate(({dialog},folder)=>{dialog.showOpenDialog=async()=>({canceled:false,filePaths:[folder]});},currentFolder);
   await page.evaluate(model=>window.localAgent.openProject('profile:'+model),profile.model_profile_id);
   const thread=options.folder?(await page.evaluate(()=>window.localAgent.getProject())).payload.active_thread:(await page.evaluate(model=>window.localAgent.createThread('profile:'+model),profile.model_profile_id)).payload.thread;
   await page.evaluate(({thread,model})=>window.localAgent.selectModel(thread,'profile:'+model),{thread:thread.id,model:profile.model_profile_id});
   await page.locator('.composer textarea').fill(goal);await page.locator('.composer textarea').press('Enter');
   const until=Date.now()+660000;
   let controlApplied=false;
   while(Date.now()<until){
    if(!controlApplied&&ownedTurn&&(options.interrupt||options.reconnect)&&events.some(e=>e.type==='plan.step.completed')){
     controlApplied=true;const originalTurn=ownedTurn;
     if(options.interrupt){await page.locator('.stop-button').click();}
     else {
      await page.evaluate(()=>{globalThis.__unifiedRestored=false;window.localAgent.onAgentEvent(e=>{if(e.type==='connection.restored')globalThis.__unifiedRestored=true;});});
      const port=(await page.evaluate(()=>window.localAgent.getAgentStatus())).port;
      await app.evaluate((_,port)=>{const sockets=process._getActiveHandles().filter(h=>h.remotePort===port&&String(h.remoteAddress).endsWith('127.0.0.1')&&!h.destroyed);if(sockets.length!==1)throw Error('OWNED_SOCKET_SCOPE');sockets[0].destroy();},port);
      await page.waitForFunction(()=>globalThis.__unifiedRestored===true,undefined,{timeout:30000});
     }
     let paused;
     for(let wait=0;wait<150;wait++){
      const state=(await page.evaluate(t=>window.localAgent.taskRequest(t,'task.runtime.list'),thread.id)).payload;
      paused=state.runtimes[0];if(paused&&['paused','cancelled','failed'].includes(paused.phase)&&state.active_turn_ids.length===0)break;
      await delay(100);
     }
     const detail={original_turn:originalTurn,original_run:paused?.id,completed_ids:paused?.plan?.steps.filter(s=>s.state==='completed').map(s=>s.id)||[],restored:!!options.reconnect,paused:paused?.phase==='paused',resumed:false};
     currentCase[options.interrupt?'interruption':'reconnect']=detail;save();
     ownedTurn=null;await delay(500);
     await page.getByRole('button',{name:'检查并继续未完成步骤',exact:true}).click();
     for(let wait=0;wait<150&&!ownedTurn;wait++)await delay(100);
     detail.resumed=!!ownedTurn&&ownedTurn!==originalTurn;
    }
    if(ownedTurn&&turnTerminal.has(ownedTurn))break;await delay(300);
   }
   if(!ownedTurn||!turnTerminal.has(ownedTurn)){if(ownedTurn)await page.evaluate(id=>window.localAgent.cancelTurn(id),ownedTurn).catch(()=>{});currentCase.result='FAIL';currentCase.reason='TURN_TIMEOUT';save();return;}
   const runs=(await page.evaluate(id=>window.localAgent.taskRequest(id,'task.runtime.list'),thread.id)).payload.runtimes;
   const runtime=runs[0];currentCase.runtime=runtime;currentCase.turn=turnTerminal.get(ownedTurn);currentCase.tools=events.filter(e=>e.type==='tool.completed');currentCase.context=events.filter(e=>e.type==='context.updated').map(e=>e.context);currentCase.dirty=shell(['status','--porcelain'],currentFolder).stdout.trim();
   const history=(await page.evaluate(()=>window.localAgent.getProject())).payload.messages;
   currentCase.answer=history.filter(m=>m.role==='assistant').at(-1)?.content||'';
   currentCase.frozen_unchanged=Object.entries(frozen).every(([file,digest])=>fs.existsSync(file)&&crypto.createHash('sha256').update(fs.readFileSync(file)).digest('hex')===digest);
   const contractArgs=['run','--locked','python','scripts/validation/unified_contract.py','--original',baselineTest,'--project',currentFolder,...(name==='change'?['--input-validation']:[]),...(['question','analysis','context','json'].includes(name)?['--structure-only']:[])];
   const originalCheck=cp.spawnSync('uv',contractArgs,{cwd:manifest.root,encoding:'utf8',windowsHide:true,timeout:60000});
   currentCase.original_test_contract={exit_code:originalCheck.status,...JSON.parse(originalCheck.stdout||'{}')};
   if(!['question','analysis','context','json'].includes(name)){
    const check=cp.spawnSync('uv',['run','--no-project','python','-m','unittest','discover','-s','tests','-v'],{cwd:currentFolder,encoding:'utf8',windowsHide:true,timeout:60000,env:{...process.env,PYTHONDONTWRITEBYTECODE:'1'}});
    currentCase.independent={exit_code:check.status,summary:(check.stdout+check.stderr).slice(-2500)};
   }
   currentCase.result=runtime&&assertion(currentCase)&&currentCase.frozen_unchanged&&originalCheck.status===0?'PASS':'FAIL';currentCase.usage=await budgetUsed();
   if(runtime){const diagnostic=(await page.evaluate(({thread,id})=>window.localAgent.taskRequest(thread,'task.runtime.diagnostics',{run_id:id}),{thread:thread.id,id:runtime.id})).payload;currentCase.diagnostics={line_count:diagnostic.markdown.split('\n').length,json_exists:fs.existsSync(diagnostic.json_path),markdown_exists:fs.existsSync(diagnostic.markdown_path)};if(currentCase.diagnostics.line_count>150||!currentCase.diagnostics.json_exists)currentCase.result='FAIL';}
   if(name==='coupon'){
    const external=cp.spawnSync('uv',['run','--locked','python','scripts/validation/coupon_contract.py',currentFolder,'-v'],{cwd:manifest.root,encoding:'utf8',windowsHide:true,timeout:60000});
    currentCase.external_contract={exit_code:external.status,summary:(external.stdout+external.stderr).slice(-2000)};
    if(external.status!==0)currentCase.result='FAIL';
   }
   save();
  }
 }catch(error){report.result='BLOCKED';report.reason=String(error.message||error).slice(0,500);}
 finally{report.elapsed_seconds=Math.round((Date.now()-started)/1000);save();if(app)await app.close().catch(()=>{});}
}
main().catch(()=>{report.result='FAIL';report.reason='CONTROLLER_UNHANDLED';save();process.exitCode=1;});
