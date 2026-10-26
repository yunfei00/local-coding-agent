/* Opt-in production IPC probes for an existing connection. Never reads a Key.
 * Does not change role bindings, budgets, chat defaults, endpoints or secrets.
 */
const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');

function importProfiles(catalog, connectionId, names) {
  const result = structuredClone(catalog);
  const added = [];
  for (const name of names) {
    if (result.profiles.some(p => p.connection_id === connectionId && p.model_id === name)) continue;
    const id = 'fetched-' + crypto.createHash('sha256').update(connectionId + '\0' + name).digest('hex').slice(0,24);
    result.profiles.push({model_profile_id:id, connection_id:connectionId, model_id:name,
      display_name:name, context_window:null, max_output_tokens:1024, temperature:null,
      pricing:null, tool_mode:'auto', supports_vision:false});
    added.push(id);
  }
  return {catalog:result, added};
}

function codingCandidate(name) {
  return /qwen|deepseek|glm|kimi|minimax/i.test(name)
    && !/image|video|wan\d|tts|asr|embedding|rerank|realtime|audio|edit|ocr|math|translation/i.test(name);
}

async function main(args) {
  const option = name => { const i=args.indexOf(name);return i<0 ? null : args[i+1]; };
  const connectionId = option('--connection');
  if (!connectionId) throw new Error('EXPLICIT_CONNECTION_REQUIRED');
  const root = path.resolve(__dirname,'../..');
  const data = option('--data-dir') || path.join(process.env.APPDATA,'local-coding-agent-desktop');
  const reportPath = path.resolve(option('--report') || path.join(root,'validation-reports/saved-model-probe.json'));
  const report = {result:'NOT RUN',connection_id:connectionId,models:[],added:[],diagnostics:[],
    started_at:new Date().toISOString(),requests:0,cost:'UNKNOWN',roles_preserved:false,
    desktop_input:'NOT RUN; this probe does not unlock or control the desktop'};
  fs.mkdirSync(path.dirname(reportPath),{recursive:true});
  const save=() => fs.writeFileSync(reportPath,JSON.stringify(report,null,2));
  let app;
  try {
    report.stage='electron_launch';save();
    const {_electron}=require('../../desktop/node_modules/playwright-core');
    const env={...process.env,LCA_DESKTOP_DATA_DIR:data,LCA_DATA_DIR:data,LCA_HEADLESS_SMOKE:'0'};
    delete env.ELECTRON_RUN_AS_NODE;
    // Production main reads its own OS-protected credential store. Neither this
    // controller nor its report receives plaintext credentials.
    app=await _electron.launch({executablePath:require('../../desktop/node_modules/electron'),
      args:[path.join(root,'desktop')],cwd:root,env,timeout:180000});
    report.stage='electron_window';save();
    const page=await app.firstWindow({timeout:45000});
    report.stage='agent_ready';save();
    await page.waitForFunction(() => !!window.localAgent,undefined,{timeout:30000});
    const readyDeadline=Date.now()+60000;
    while ((await page.evaluate(()=>window.localAgent.getAgentStatus())).state!=='ready') {
      if (Date.now()>=readyDeadline) throw new Error('AGENT_READY_TIMEOUT');
      await new Promise(resolve=>setTimeout(resolve,200));
    }
    await page.exposeFunction('lcaProbeError', event => {
      // Agent send_error has already redacted its exact in-memory secrets.
      // Only configuration errors are retained; no request bodies or stacks.
      if (event.type==='error') {
        report.configuration_error={code:event.payload.code,message:event.payload.message};save();
      }
    });
    await page.evaluate(()=>window.localAgent.onAgentEvent(event=>{
      if(event.type==='error') void window.lcaProbeError(event);
    }));
    const request=(type,payload={}) => page.evaluate(async ({type,payload}) =>
      window.localAgent.taskRequest('',type,payload),{type,payload}).then(r => r.payload);
    report.stage='credential_status';save();
    const credential=await request('task.credential.status');
    if (credential.mode!=='os_protected' || !credential.configured.includes('connection-'+connectionId))
      throw new Error('PROTECTED_CREDENTIAL_UNAVAILABLE');
    report.stage='catalog_get';save();
    const before=await request('task.catalog.get');
    const connection=before.catalog.connections.find(c=>c.connection_id===connectionId);
    if (!connection?.enabled || connection.provider_type!=='openai_compatible') throw new Error('ENABLED_API_CONNECTION_REQUIRED');
    report.connection_name=connection.display_name;
    report.stage='model_list';save();
    const fetched=await request('task.connection.test',{connection_id:connectionId});
    report.connection_online=fetched.online;
    report.models=(fetched.models || []).map(m=>m.name);
    if (!fetched.online) {report.error_code=fetched.error?.code || 'MODEL_LIST_FAILED';save();return;}
    const explicit=option('--models')?.split(',').filter(Boolean);
    const selected=explicit || report.models.filter(codingCandidate);
    if (selected.some(name=>!report.models.includes(name))) throw new Error('SELECTED_MODEL_NOT_FETCHED');
    report.selected=selected;
    if (args.includes('--import')) {
      report.stage='catalog_import';save();
      const imported=importProfiles(before.catalog,connectionId,selected);
      await request('task.catalog.update',{catalog:imported.catalog,config:before.config});
      report.added=imported.added;
    }
    save();
    if (args.includes('--live')) {
      for (const name of selected) {
        report.stage='model_diagnostic';save();
        const current=await request('task.catalog.get');
        const profile=current.catalog.profiles.find(p=>p.connection_id===connectionId && p.model_id===name);
        if (!profile) {report.diagnostics.push({model_id:name,result:'NOT RUN',reason:'PROFILE_NOT_SAVED'});continue;}
        const result=await request('task.model.diagnostic',{connection_id:connectionId,
          model_profile_id:profile.model_profile_id,live:true,vision:true});
        report.diagnostics.push(result);
        report.requests+=result.requests || 0;
        // A fetched name is not evidence of vision. Promote only an actual
        // random-pixel challenge PASS; preserve existing explicit declarations.
        if (result.vision==='PASS' && !profile.supports_vision && args.includes('--import')) {
          const latest=await request('task.catalog.get');
          const p=latest.catalog.profiles.find(p=>p.model_profile_id===profile.model_profile_id);
          p.supports_vision=true;
          await request('task.catalog.update',{catalog:latest.catalog,config:latest.config});
        }
        save();
        console.log(JSON.stringify({model:name,text:result.text,vision:result.vision,
          tools:result.tools,requests:result.requests,errors:result.errors}));
      }
    }
    const after=await request('task.catalog.get');
    report.roles_preserved=JSON.stringify(before.config)===JSON.stringify(after.config)
      && before.chat_default===after.chat_default && before.chat_vision===after.chat_vision;
    report.result=report.roles_preserved ? 'PASS' : 'FAIL';
    report.note='PASS means inventory/import completed with routing preserved. See each diagnostic for model capabilities; not autonomous coding or native desktop acceptance.';
  } catch (error) {
    report.result='FAIL';
    // Do not emit IPC exception messages or stacks that can include private data.
    report.error_code=['EXPLICIT_CONNECTION_REQUIRED','PROTECTED_CREDENTIAL_UNAVAILABLE',
      'ENABLED_API_CONNECTION_REQUIRED','SELECTED_MODEL_NOT_FETCHED'].includes(error.message) ? error.message : error.name;
    report.error_category=/Process failed to launch/i.test(error.message) ? 'PROCESS_FAILED_TO_LAUNCH'
      : /closed|Target page/i.test(error.message) ? 'ELECTRON_CLOSED'
      : /Timeout/i.test(error.name) ? 'TIMEOUT' : 'IPC_OR_CONTROLLER_FAILURE';
    process.exitCode=2;
  } finally {
    report.ended_at=new Date().toISOString();save();
    if (app) await app.close();
  }
  console.log(JSON.stringify({result:report.result,models:report.models.length,added:report.added.length,requests:report.requests}));
}

module.exports={importProfiles,codingCandidate};
if (require.main===module) main(process.argv.slice(2)).catch(()=>{process.exitCode=2;});
