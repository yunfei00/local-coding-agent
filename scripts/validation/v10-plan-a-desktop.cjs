/* Real installed Electron UI/IPC/backend + real streamed loopback files; release metadata and OS opening controlled. */
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict'),http=require('node:http'),crypto=require('node:crypto');
const {_electron}=require('../../desktop/node_modules/playwright-core');
const {closeOwnedApplication}=require('./live_gui_guard.cjs');
const root=path.resolve(__dirname,'../..'),exe=path.resolve(process.argv[2]),out=path.resolve(process.argv[3]);
assert(exe.startsWith(path.join(root,'build')+path.sep)&&!fs.existsSync(out)&&out.startsWith(path.join(root,'validation-reports')+path.sep));fs.mkdirSync(out,{recursive:true});
const data=Buffer.from('CONTROLLED UPDATE FILE, NEVER EXECUTE\n'.repeat(5000)),hash=crypto.createHash('sha256').update(data).digest('hex'),name='Local-Coding-Agent-1.0.1-x64-Setup.exe';let mode='slow',app;
const server=http.createServer((req,res)=>{if(req.url.endsWith('SHA256SUMS.txt'))return res.end(`${mode==='bad'?'0'.repeat(64):hash}  ${name}\n`);res.setHeader('Content-Length',data.length);let i=0;const send=()=>{if(res.destroyed)return;if(i>=data.length)return res.end();res.write(data.subarray(i,i+4096));i+=4096;setTimeout(send,mode==='slow'?30:1);};send();});
const report={result:'RUNNING',real:'installed UI, IPC, backend, HTTP and files',mock:'release metadata namespace, network mapping to loopback, native confirmation, OS open callbacks; inert fixture never executed',checks:[]};
async function launch(){
 const env={...process.env,LCA_DATA_DIR:path.join(out,'agent'),LCA_DESKTOP_DATA_DIR:path.join(out,'desktop'),LCA_HEADLESS_SMOKE:'1',LCA_PROVIDER:'openai_compatible',LCA_OPENAI_BASE_URL:'http://127.0.0.1:1/v1',LCA_OPENAI_API_KEY:'',LCA_OLLAMA_URL:'http://127.0.0.1:1'};for(const key of ['ELECTRON_RUN_AS_NODE','LCA_PACKAGED_SMOKE_FILE'])delete env[key];
 app=await _electron.launch({executablePath:exe,args:['--disable-gpu'],env,cwd:out,timeout:60000});const page=await app.firstWindow();await page.waitForFunction(()=>!!window.localAgent);
 const deadline=Date.now()+45000;let ready=false;while(Date.now()<deadline){ready=(await page.evaluate(()=>window.localAgent.getAgentStatus())).state==='ready';if(ready)break;await new Promise(r=>setTimeout(r,100));}assert(ready);
 await app.evaluate(({app,dialog,shell},{port,name,size,hash})=>{
  const require=process.mainModule.require.bind(process.mainModule),path=require('node:path'),http=require('node:http');
  const module=require(path.join(app.getAppPath(),'dist-electron/updateManager.js')),original=module.UpdateManager.prototype.check;
  module.UpdateManager.prototype.check=function(){this.fetchMetadata=async()=>({tag_name:'v1.0.1',body:'受控方案A验收，不是真实线上新版',assets:[name,'SHA256SUMS.txt'].map(n=>({name:n,size:n===name?size:200,browser_download_url:'https://github.com/yunfei00/local-coding-agent/releases/download/v1.0.1/'+n}))});this.download=module.assetDownloader((url,options,callback)=>http.get('http://127.0.0.1:'+port+url.pathname,options,callback));return original.call(this);};
  globalThis.updateOpenCalls=[];globalThis.updateFolders=[];shell.openPath=async file=>{globalThis.updateOpenCalls.push(file);return '';};shell.showItemInFolder=file=>globalThis.updateFolders.push(file);dialog.showMessageBox=async()=>({response:1,checkboxChecked:false});
 },{port:server.address().port,name,size:data.length,hash});
 await page.getByRole('button',{name:'Settings',exact:true}).click();await page.getByRole('button',{name:'关于',exact:true}).click();return page;
}
async function close(){if(app){Object.assign(report,await closeOwnedApplication(app,app.process()));app=null;}}
(async()=>{try{
 await new Promise(r=>server.listen(0,'127.0.0.1',r));let page=await launch();const before=await page.evaluate(()=>window.localAgent.getAgentStatus());
 await page.getByRole('button',{name:'检查更新',exact:true}).click();await page.waitForFunction(()=>document.querySelector('[aria-label="软件更新"]')?.textContent.includes('发现新版本'));
 await page.getByRole('button',{name:'下载更新',exact:true}).click();await page.waitForFunction(()=>!!document.querySelector('progress')&&document.querySelector('[aria-label="软件更新"]')?.textContent.includes('字节'));
 await page.getByRole('button',{name:'取消下载',exact:true}).click();await page.waitForFunction(()=>document.querySelector('[aria-label="软件更新"]')?.textContent.includes('已取消下载'));report.checks.push('真实安装版进度与取消，未关闭Agent');
 mode='bad';await page.getByRole('button',{name:'重新下载',exact:true}).click();await page.waitForFunction(()=>document.querySelector('[aria-label="软件更新"]')?.textContent.includes('校验失败'));assert(await page.getByRole('button',{name:'打开安装包',exact:true}).isDisabled());report.checks.push('真实校验失败阻止打开');
 mode='normal';await page.getByRole('button',{name:'重新下载',exact:true}).click();await page.waitForFunction(()=>document.querySelector('[aria-label="软件更新"]')?.textContent.includes('请关闭软件后手动安装'));
 assert.equal((await app.evaluate(()=>globalThis.updateOpenCalls)).length,0);const after=await page.evaluate(()=>window.localAgent.getAgentStatus());assert.equal(after.state,'ready');assert.equal(after.port,before.port);
 await page.getByRole('button',{name:'打开所在文件夹',exact:true}).click();await page.getByRole('button',{name:'打开安装包',exact:true}).click();const opened=await app.evaluate(()=>globalThis.updateOpenCalls);assert.equal(opened.length,1);assert(opened[0].startsWith(path.join(out,'desktop','updates')+path.sep));assert.equal(crypto.createHash('sha256').update(fs.readFileSync(opened[0])).digest('hex'),hash);assert.equal((await app.evaluate(()=>globalThis.updateFolders)).length,1);report.checks.push('只有主动点击才调用系统打开；未暂停后端或退出');
 await close();page=await launch();await page.waitForFunction(()=>document.querySelector('[aria-label="软件更新"]')?.textContent.includes('已恢复并重新校验'));report.checks.push('安装版重启后真实缓存重校验');await close();
 report.result='PASS';
}catch(e){report.result='FAIL';report.error=String(e.stack||e).slice(0,2200);process.exitCode=1;}finally{await close();server.closeAllConnections();await new Promise(r=>server.close(r));fs.writeFileSync(path.join(out,'report.json'),JSON.stringify(report,null,2));console.log(JSON.stringify(report,null,2));}})();
