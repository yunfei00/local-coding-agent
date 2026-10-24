/* Controller only: real Electron -> existing IPC -> real TaskService/Provider.
 * No model mock, file repair, alternate agent loop, or credential decryption.
 * Invoke through the uv Python entry, which prepares the isolated fixture.
 */
const fs = require('node:fs');
const path = require('node:path');

const GOAL = `请检查当前 Electron + React + TypeScript 工程中的 Settings 页面。
目前存在输入框无法编辑，以及点击 Save 后保存状态没有正确更新的问题。
请自主定位并修复这两个问题。
先读取项目代码和现有测试，不修改或弱化测试及 GUI 验收契约，修改实际业务代码。
运行 TypeScript 类型检查、单元测试、构建，启动 Electron 程序。
查找实际 Windows 窗口、检查 UIA 控件、截取真实 GUI 图像，在授权范围内让视觉模型观察截图。
点击 Settings，输入普通测试文字，点击 Save，检查实际显示和持久化结果。
如果失败，根据真实失败原因继续修复，重新运行程序和验收。
最终输出测试结果、修改文件、Git Diff、API 使用情况。不要自动提交或推送实验工程。
安全范围：只操作本临时工程和它启动的精确标题 M5 Electron acceptance 的窗口。
只允许上传这个受控窗口的截图，不能上传整个桌面或其他窗口。
使用 start_process 启动 npm start；从真实 M5_ELECTRON_READY 输出读取 pid，按 pid 枚举窗口。
不要读取公司文件、凭据或其他用户窗口。不要修改 package scripts、测试或 .lca 契约。
依赖需要 npm ci --no-audit --no-fund。可以合并独立只读检查到同一轮工具调用以节约预算。`;

const delay = ms => new Promise(resolve => setTimeout(resolve, ms));
const TERMINAL = new Set(['paused','failed','cancelled','completed','awaiting_approval']);

function approvalAllowed(payload, workspace, ownedPids, phase) {
  const a = payload.arguments || {}, tool = payload.tool;
  if (tool === 'git_worktree_create') return /^lca\/task-[a-zA-Z0-9_-]+$/.test(a.branch || '');
  // The independent verifier filters by its launched Job before using results;
  // model-facing enumeration must be PID scoped so private window titles never
  // enter the online model context.
  if (tool === 'desktop_list_windows') return a.pid ? ownedPids.has(a.pid) : phase === 'verifying';
  if (tool.startsWith('desktop_')) {
    const w = a.target_window;
    return !!w && w.title === 'M5 Electron acceptance' && ownedPids.has(w.pid)
      && a.scope !== 'screen' && !['desktop_keypress','desktop_scroll'].includes(tool)
      && (tool !== 'desktop_click' || a.selector && ['Settings','Save'].includes(a.selector.name));
  }
  if (tool === 'run_command' || tool === 'start_process') {
    return /^(npm (ci --no-audit --no-fund|run (typecheck|build)|test|start)|git (diff( --check)?|status( -sb)?))$/.test(a.command || '')
      && (!a.cwd || a.cwd === '.' || path.resolve(a.cwd) === path.resolve(workspace || '.'));
  }
  return false; // No blanket Full Access, allow_turn, publishing or outside paths.
}

function safeCall(call) {
  const keys = ['call_id','sequence','phase','started_at','ended_at','http_status','response_type',
    'request_sent','request_dispatched','finish_reason','response_form','failure_reason','error_code',
    'connection_id','provider','provider_type','model_profile_id','input_tokens','output_tokens',
    'cached_tokens','estimated','actual_cost','initial_reserved_tokens','released_tokens','settlement',
    'wire_images','tool_schema_count'];
  return {id:call.id, model:call.model, role:call.role, status:call.status,
    reserved_tokens:call.reserved_tokens, ...Object.fromEntries(keys.filter(k => call.usage?.[k] !== undefined).map(k => [k,call.usage[k]]))};
}

function finalResult(task, tools) {
  const verifications = task.verification || [];
  const calls = (task.calls || []).map(safeCall);
  const real = calls.filter(c => c.request_sent === true && c.http_status === 200);
  const gui = verifications.find(v => v.command === 'GUI acceptance');
  const evidence = gui?.evidence || [];
  const image = evidence.some(e => e.tool === 'desktop_screenshot' && e.ok && e.sha256);
  const observation = evidence.find(e => e.tool === 'vision_observer')?.observation;
  const passed = task.status === 'awaiting_approval' && verifications.length >= 5
    && verifications.every(v => v.ok) && tools.some(t => t.ok && ['apply_patch','write_file'].includes(t.name))
    && real.length > 0 && real.every(c => c.estimated === false)
    && image && real.some(c => c.role === 'vision-observer' && c.tool_schema_count === 0
      && c.wire_images?.some(i => i.mime_type === 'image/jpeg' && i.bytes > 0 && i.sha256))
    && observation?.observations?.length > 0 && observation.errors?.length === 0;
  return {result:passed ? 'PASS' : 'FAIL', reason:task.last_error?.code || task.reason || task.status,
    last_error:task.last_error || null,
    status_reason:task.reason,
    task_id:task.id, final_status:task.status, workspace:task.workspace,
    acceptance_baseline:task.acceptance_baseline, usage:task.usage, calls,
    paid_requests:calls.filter(c => c.request_sent).length,
    attempts:task.attempts, repairs:task.repairs,
    verification:verifications, verification_history:task.verification_history,
    transitions:task.transitions, tool_count:tools.length,
    function_call_count:tools.filter(t => t.model_requested).length,
    vision_observation:observation || null,
    // A schema-valid observation is protocol evidence; review content in report.
    vision_content_review:'Required: compare observation with controlled capture/UIA',
    tools};
}

async function main(manifest) {
  const { _electron } = require('../../desktop/node_modules/playwright-core');
  const root = path.resolve(__dirname,'../..');
  let app, page, thread, task, stage = 'electron_launch';
  const initial = JSON.parse(fs.readFileSync(manifest.report,'utf8'));
  const events = [], tools = [], approvals = [], ownedPids = new Set(), requests = new Map();
  const processFiles = () => {
    const file = task?.workspace && path.join(task.workspace,'.runtime/process.json');
    if (file && fs.existsSync(file)) {
      const value = JSON.parse(fs.readFileSync(file,'utf8'));
      for (const pid of [value.pid, ...(value.children || [])]) if (Number.isInteger(pid)) ownedPids.add(pid);
    }
  };
  const save = extra => fs.writeFileSync(manifest.report,JSON.stringify({...initial,...extra},null,2));
  try {
    const environment = {...process.env, LCA_DESKTOP_DATA_DIR:manifest.credential_data, LCA_DATA_DIR:manifest.data,
      LCA_HEADLESS_SMOKE:'0', LCA_OPENAI_API_KEY:'', LCA_PROVIDER:'openai_compatible', LCA_OPENAI_MODEL:'',
      LCA_OPENAI_BASE_URL:'http://127.0.0.1:1/v1'};
    delete environment.ELECTRON_RUN_AS_NODE;
    app = await _electron.launch({executablePath:require('../../desktop/node_modules/electron'),
      args:[path.join(root,'desktop')], cwd:root, env:environment, timeout:45000});
    page = await app.firstWindow();
    stage = 'agent_ready';
    await page.waitForFunction(() => !!window.localAgent,undefined,{timeout:30000});
    const ready = Date.now() + 45000;
    while (Date.now() < ready) {
      const state = await page.evaluate(() => window.localAgent.getAgentStatus());
      if (state.state === 'ready') break;
      if (state.state === 'error') throw new Error('AGENT_START_FAILED');
      await delay(200);
    }
    stage = 'protected_credential_status';
    const credential = (await page.evaluate(() => window.localAgent.taskRequest('','task.credential.status'))).payload;
    initial.credential_mode = credential.mode;
    const expected = 'connection-' + manifest.executor.connection_id;
    if (credential.mode !== 'os_protected' || !credential.configured.includes(expected)) {
      save({result:'NOT RUN', reason:'PROTECTED_CREDENTIAL_UNAVAILABLE', paid_requests:0});
      return;
    }
    await page.exposeFunction('lcaAcceptanceEvent', async event => {
      const p = event.payload || {};
      if (event.type === 'task.updated' && p.task) task = p.task;
      if (event.type === 'approval.requested') {
        processFiles();
        const allowed = approvalAllowed(p, task?.workspace, ownedPids, task?.status);
        approvals.push({tool:p.tool, decision:allowed ? 'allow_once':'deny', risk:p.risk});
        await page.evaluate(({id, decision, turn}) => window.localAgent.respondApproval(id,decision,turn),
          {id:p.approval_id, decision:allowed ? 'allow_once':'deny', turn:event.turn_id});
      }
      if (event.type === 'tool.requested') {
        const a = p.arguments || {};
        requests.set(p.tool_call_id,{name:p.name,
          ...Object.fromEntries(['path','command'].filter(k=>typeof a[k]==='string').map(k=>[k,a[k].slice(0,2000)]))});
      }
      if (event.type === 'tool.completed') {
        const r = p.result || {};
        tools.push({...requests.get(p.tool_call_id), model_requested:requests.has(p.tool_call_id), name:p.name, ok:!!r.ok, error_code:r.error?.code,
          changed_paths:r.changed_paths || [], exit_code:r.exit_code, duration_ms:r.duration_ms});
        processFiles();
      }
      if (['model.active','verification.progress','vision.observed'].includes(event.type)) {
        events.push({type:event.type, at:event.timestamp, ...Object.fromEntries(
          ['role','model','connection_id','model_profile_id','stage','state','ok','image_attached','attachment_transport'].filter(k => p[k] !== undefined).map(k=>[k,p[k]]))});
      }
    });
    await page.evaluate(() => window.localAgent.onAgentEvent(e => {void window.lcaAcceptanceEvent(e);}));
    // Only the native file-picker is controlled; all project/task operations are production IPC.
    await app.evaluate(({dialog}, folder) => {dialog.showOpenDialog = async () => ({canceled:false,filePaths:[folder]});},manifest.source);
    stage = 'project_and_thread';
    await page.evaluate(profile => window.localAgent.openProject('profile:'+profile),manifest.executor.model_profile_id);
    const created = await page.evaluate(profile => window.localAgent.createThread('profile:'+profile),manifest.executor.model_profile_id);
    thread = created.payload.thread?.id || created.payload.active_thread?.id;
    if (!thread) {
      const project = await page.evaluate(() => window.localAgent.getProject());
      thread = project.payload.active_thread.id;
    }
    await page.evaluate(() => window.localAgent.setPermission('workspace'));
    const started = Date.now();
    stage = 'task_start';
    const response = await page.evaluate(({thread, goal, config}) => window.localAgent.taskRequest(thread,'task.start',{goal,config}),
      {thread, goal:GOAL, config:manifest.config});
    task = response.payload.task;
    if (!task) throw new Error('TASK_NOT_CREATED');
    stage = 'task_running';
    save({task_id:task.id, source:manifest.source, result:'RUNNING', paid_requests:0});
    let lastStatus = '';
    while (Date.now()-started < manifest.config.budget.task_seconds*1000) {
      const reply = await page.evaluate(thread => window.localAgent.taskRequest(thread,'task.list'),thread);
      task = reply.payload.tasks.find(t => t.id === task.id);
      processFiles();
      const progress = `${task.status} calls=${task.usage.api_calls} tokens=${task.usage.reserved_tokens}`;
      if (progress !== lastStatus) {console.log(progress);lastStatus=progress;}
      save({...finalResult(task,tools), result:'RUNNING', source:manifest.source, events, approvals});
      if (TERMINAL.has(task.status)) break;
      await delay(1000);
    }
    if (!TERMINAL.has(task.status)) {
      await page.evaluate(({thread,id})=>window.localAgent.taskRequest(thread,'task.cancel',{task_id:id}),{thread,id:task.id});
      task = (await page.evaluate(thread=>window.localAgent.taskRequest(thread,'task.list'),thread)).payload.tasks.find(t=>t.id===task.id);
    }
    const result = finalResult(task,tools);
    save({...result, source:manifest.source, events, approvals, active_seconds:(Date.now()-started)/1000});
    console.log(JSON.stringify({task_id:task.id,result:result.result,reason:result.reason,paid_requests:result.paid_requests}));
  } catch (error) {
    // Error strings/stacks from requests or Electron may contain private data.
    save({...(task ? finalResult(task,tools):{}), result:task ? 'FAIL':'NOT RUN',
      reason:'CONTROLLER_'+error.name, controller_stage:stage, events, approvals, source:manifest.source});
    process.exitCode = 2;
  } finally {
    if (task && page && !TERMINAL.has(task.status)) {
      try {
        await page.evaluate(({thread,id})=>window.localAgent.taskRequest(thread,'task.pause',{task_id:id}),{thread,id:task.id});
        const latest = (await page.evaluate(thread=>window.localAgent.taskRequest(thread,'task.list'),thread)).payload.tasks.find(t=>t.id===task.id);
        const last = JSON.parse(fs.readFileSync(manifest.report,'utf8'));
        save({...last,...finalResult(latest,tools),result:'FAIL',reason:last.reason,events,approvals});
      } catch {
        const last = JSON.parse(fs.readFileSync(manifest.report,'utf8'));
        save({...last,result:'FAIL',paid_requests:null,usage_uncertain:true});
      }
    }
    if (app) await app.close(); // existing shutdown kills managed Task Job trees
    const cleanup = [];
    for (const pid of ownedPids) {
      let alive = true;
      for (let retry=0; retry<20; retry++) {
        try {process.kill(pid,0);} catch {alive=false;break;}
        await delay(100);
      }
      cleanup.push({pid,exited:!alive});
    }
    const last = JSON.parse(fs.readFileSync(manifest.report,'utf8'));
    if (cleanup.some(p=>!p.exited)) {last.result='FAIL';last.reason='OWNED_PROCESS_CLEANUP_FAILED';}
    fs.writeFileSync(manifest.report,JSON.stringify({...last,cleanup},null,2));
  }
}

module.exports = {approvalAllowed, safeCall, finalResult, GOAL};
if (require.main === module) main(JSON.parse(fs.readFileSync(process.argv[2],'utf8'))).catch(() => {process.exitCode=2;});
