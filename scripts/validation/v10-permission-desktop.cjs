/* Real installed Electron IPC + real backend; only native dialog choices mocked.
 * No model generation, no credentials, no user data profile or invented task state.
 */
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const {_electron}=require('../../desktop/node_modules/playwright-core');
const {closeOwnedApplication}=require('./live_gui_guard.cjs');
const root=path.resolve(__dirname,'../..'),exe=path.resolve(process.argv[2]||''),output=path.resolve(process.argv[3]||'validation-reports/v10-permission-desktop');
assert(exe.startsWith(path.join(root,'build')+path.sep)&&fs.existsSync(exe),'Owned installed executable required');
assert(output.startsWith(path.join(root,'validation-reports')+path.sep)&&!fs.existsSync(output),'New isolated evidence directory required');
fs.mkdirSync(output,{recursive:true});
const report={result:'RUNNING',native_dialog:'MOCKED; not counted as real Windows dialog acceptance',generation:'NOT_RUN',checks:[]};
let app;
async function launch(){
 const env={...process.env,LCA_DATA_DIR:path.join(output,'data'),LCA_DESKTOP_DATA_DIR:path.join(output,'desktop'),LCA_OLLAMA_URL:'http://127.0.0.1:1',LCA_PROVIDER:'openai_compatible',LCA_OPENAI_BASE_URL:'http://127.0.0.1:1/v1',LCA_OPENAI_API_KEY:''};
 for(const name of ['ELECTRON_RUN_AS_NODE','LCA_PACKAGED_SMOKE_FILE','LCA_HEADLESS_SMOKE','LCA_UPDATE_CHECK_URL'])delete env[name];
 app=await _electron.launch({executablePath:exe,args:['--disable-gpu'],env,cwd:root,timeout:60000});
 app.process().stdout?.on('data',data=>{report.process_events=(report.process_events||[]).concat(String(data).split('\n').filter(line=>/WebSocket|error|Error|Exception/.test(line)).map(line=>line.slice(0,500))).slice(-30);});
 const page=await app.firstWindow();await page.waitForFunction(()=>!!window.localAgent);
 // Playwright polling predicates are synchronous; a Promise is truthy even
 // when it eventually resolves false. Poll actual awaited IPC in the driver.
 let connected=false;const deadline=Date.now()+45000;
 while(Date.now()<deadline){try{connected=!!(await page.evaluate(()=>window.localAgent.getPermission())).payload?.mode;}catch{}if(connected)break;await new Promise(resolve=>setTimeout(resolve,200));}
 assert(connected,'Authenticated backend permission RPC did not become ready');
 assert.equal(await app.evaluate(({app})=>app.isPackaged),true);
 assert.equal(await app.evaluate(({app})=>app.getVersion()),'1.0.0');
 await app.evaluate(({dialog})=>{globalThis.permissionDialogs=[];globalThis.permissionAnswer=0;dialog.showMessageBox=async options=>{globalThis.permissionDialogs.push({title:options.title,detail:options.detail});return {response:globalThis.permissionAnswer,checkboxChecked:false};};});
 return page;
}
async function close(){if(app){Object.assign(report,await closeOwnedApplication(app,app.process()));app=null;}}
(async()=>{
 try{
  let page=await launch();
  await assert.rejects(()=>page.evaluate(()=>window.localAgent.setPermission('full_access')),/未启用完全访问/);
  assert.equal((await page.evaluate(()=>window.localAgent.getPermission())).payload.mode,'workspace');report.checks.push('首次拒绝不授予完全访问');
  await app.evaluate(()=>{globalThis.permissionAnswer=1;});
  await page.evaluate(()=>window.localAgent.setPermission('full_access'));
  await page.waitForFunction(()=>document.querySelector('.permission-select')?.value==='full_access');
  await page.evaluate(()=>window.localAgent.setPermission('workspace'));await page.evaluate(()=>window.localAgent.setPermission('full_access'));
  const dialogs=await app.evaluate(()=>globalThis.permissionDialogs);assert.equal(dialogs.length,2);assert(dialogs.every(d=>d.detail.includes('UAC')&&d.detail.includes('脱敏截图')));
  report.checks.push('明确说明风险后一次授权；再次启用不重复确认');
  await page.evaluate(()=>window.localAgent.setPermission('read_only'));await close();
  page=await launch();assert.equal((await page.evaluate(()=>window.localAgent.getPermission())).payload.mode,'read_only');
  await page.evaluate(()=>window.localAgent.setPermission('full_access'));assert.equal((await app.evaluate(()=>globalThis.permissionDialogs)).length,0);
  report.checks.push('实际安装版重启后恢复撤销状态与一次确认记录');
  // No update must fail before any installer consent/download; if a future offer
  // appears, the mocked Cancel still prevents downloading software.
  try{const result=await page.evaluate(()=>window.localAgent.downloadUpdate());report.update={status:result?.cancelled?'CANCELLED_OFFER':'UNEXPECTED',result};}
  catch(error){const text=String(error.message);report.update={status:text.includes('当前没有可用更新')?'PASS_NO_UPDATE':text.includes('仅支持 Windows')?'FAIL_INSTALLED_DETECTION':'BLOCKED_NETWORK',summary:text.slice(0,400)};}
  assert.notEqual(report.update.status,'FAIL_INSTALLED_DETECTION');
  await page.evaluate(()=>window.localAgent.setPermission('read_only'));
  assert.equal((await page.evaluate(()=>window.localAgent.getPermission())).payload.mode,'read_only');
  report.checks.push('设置入口可撤销授权，新状态由真实后端返回');
  report.result='PASS';
 }catch(error){report.result='FAIL';report.error=String(error.stack||error).slice(0,1800);process.exitCode=1;}
 finally{await close();fs.writeFileSync(path.join(output,'report.json'),JSON.stringify(report,null,2));console.log(JSON.stringify(report,null,2));}
})();
