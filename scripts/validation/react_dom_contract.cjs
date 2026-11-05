/* Independent DOM contract for the synthetic React project, not OS GUI input. */
const fs=require('node:fs'),path=require('node:path'),http=require('node:http'),os=require('node:os');
async function checkReact(reportPath){
 const {BrowserWindow}=require('electron');
 const report=JSON.parse(fs.readFileSync(reportPath,'utf8'));
 const progress=stage=>fs.writeFileSync(path.join(path.dirname(reportPath),'react-dom-progress.json'),JSON.stringify({stage,free_bytes:os.freemem(),at:new Date().toISOString()}));
 progress('contract_started');
 const root=path.resolve(__dirname,'../../validation-reports');
 const inside=value=>{const relative=path.relative(root,fs.realpathSync(value));return relative!==''&&!relative.startsWith('..')&&!path.isAbsolute(relative);};
 if(!inside(reportPath))throw Error('REPORT_BOUNDARY');
 for(const item of report.cases.filter(c=>c.name==='workflow-react'&&c.result==='PASS')){
  if(os.freemem()<512*1024*1024){item.react_ui={result:'BLOCKED_RESOURCE'};report.result='BLOCKED';continue;}
  const dist=path.join(item.folder,'frontend/dist');if(!inside(dist))throw Error('FIXTURE_BOUNDARY');
  const server=http.createServer((req,res)=>{
   const candidate=path.resolve(dist,'.'+decodeURIComponent(req.url.split('?')[0]));
   if(!candidate.startsWith(dist+path.sep)&&candidate!==dist){res.writeHead(403);res.end();return;}
   const file=candidate===dist?path.join(dist,'index.html'):candidate;
   try{res.setHeader('Content-Type',file.endsWith('.js')?'text/javascript':file.endsWith('.css')?'text/css':'text/html');res.end(fs.readFileSync(file));}catch{res.writeHead(404);res.end();}
  });
  await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));let window;
  try{
   window=new BrowserWindow({show:false,width:900,height:650,webPreferences:{nodeIntegration:false,contextIsolation:true,sandbox:true}});
   progress('window_created');
   await Promise.race([window.loadURL(`http://127.0.0.1:${server.address().port}/`),new Promise((_,reject)=>setTimeout(()=>reject(Error('DOM_LOAD_TIMEOUT')),15000))]);
   progress('page_loaded');
   const result=await window.webContents.executeJavaScript(`(async()=>{
    const wait=()=>new Promise(r=>setTimeout(r,100));await wait();
    const inputs=[...document.querySelectorAll('input[type="number"]')];
    const labels=inputs.map(input=>[...(input.labels||[])].map(label=>label.textContent.trim()).join(' '));
    const first=inputs.find((input,i)=>labels[i].includes('第一个数'));const second=inputs.find((input,i)=>labels[i].includes('第二个数'));
    const button=[...document.querySelectorAll('button')].find(b=>b.textContent.trim()==='计算');
    if(!first||!second||!button)return {result:'FAIL',labels,reason:'缺少约定的输入标签或计算按钮'};
    const set=Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value').set;
    set.call(first,'3');first.dispatchEvent(new Event('input',{bubbles:true}));await wait();
    set.call(second,'2');second.dispatchEvent(new Event('input',{bubbles:true}));await wait();button.click();await wait();
    const text=document.body.innerText;return {result:/结果\\s*[:：]\\s*5/.test(text)?'PASS':'FAIL',labels,text:text.slice(0,1000)};
   })()`,true);
   progress('dom_checked');
   const screenshot=path.join(path.dirname(reportPath),'react-dom-result.png');
   fs.writeFileSync(screenshot,(await window.webContents.capturePage()).toPNG());
   item.react_ui={...result,screenshot,scope:'real Chromium DOM; no Windows input/UIA claim'};
   if(result.result!=='PASS'){item.result='FAIL';report.result='PARTIAL';}
  }finally{if(window&&!window.isDestroyed())window.destroy();await new Promise(resolve=>server.close(resolve));}
 }
 fs.writeFileSync(reportPath,JSON.stringify(report,null,2));
 return report.result==='PASS'?0:1;
}
module.exports={checkReact};
if(path.resolve(process.argv[1]||'')===__filename){const {app}=require('electron');process.stdout.write(JSON.stringify({main_match:require.main===module,entry_started:true})+'\n');app.commandLine.appendSwitch('disable-gpu');app.whenReady().then(()=>checkReact(process.argv[2])).then(code=>app.exit(code)).catch(()=>{process.stderr.write('React DOM contract failed; inspect controlled report.\n');app.exit(1);});}
