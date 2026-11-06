/* Actual Setup/Portable runtime + actual composer/WS/file write, Mock loopback model only. */
const fs=require('node:fs'),path=require('node:path'),http=require('node:http'),crypto=require('node:crypto'),cp=require('node:child_process');
const root=path.resolve(__dirname,'../..'),exe=path.resolve(process.argv[2]),output=path.resolve(process.argv[3]);
if(!exe.startsWith(root+path.sep)||!output.startsWith(path.join(root,'build')+path.sep)||fs.existsSync(output))throw Error('New owned build output required');
fs.mkdirSync(output,{recursive:true});
let nonce='',calls=0;
const server=http.createServer((req,res)=>{
 if(req.url.endsWith('/models')){res.setHeader('Content-Type','application/json');res.end(JSON.stringify({data:[{id:'packaged-smoke-model'}]}));return;}
 let body='';req.on('data',data=>body+=data);req.on('end',()=>{
  const p=JSON.parse(body||'{}');calls++;
  const written=p.messages?.some(m=>m.role==='tool'&&String(m.content).includes('packaged-chat.txt'));
  const delta=written?{content:nonce}:{tool_calls:[{index:0,id:'owned-write-'+calls,type:'function',function:{name:'write_file',arguments:JSON.stringify({path:'packaged-chat.txt',content:nonce})}}]};
  res.writeHead(200,{'Content-Type':'text/event-stream'});
  res.end('data: '+JSON.stringify({choices:[{index:0,delta,finish_reason:written?'stop':'tool_calls'}],usage:{prompt_tokens:1,completion_tokens:1,total_tokens:2}})+'\n\ndata: [DONE]\n\n');
 });
});
(async()=>{
 const report={result:'RUNNING',model:'MOCK_LOOPBACK',executable:path.basename(exe),runs:[]};let child;
 try{
  await new Promise(r=>server.listen(0,'127.0.0.1',r));
  for(let run=0;run<2;run++){
   nonce='PACKAGED_CHAT_'+crypto.randomBytes(8).toString('hex');const marker=path.join(output,'marker-'+run+'.json');
   const env={...process.env,LCA_PACKAGED_SMOKE_FILE:marker,LCA_PACKAGED_CHAT_ACCEPTANCE:'1',LCA_PACKAGED_CHAT_NONCE:nonce,LCA_DATA_DIR:path.join(output,'data'),LCA_DESKTOP_DATA_DIR:path.join(output,'desktop'),LCA_HEADLESS_SMOKE:'1',LCA_PROVIDER:'openai_compatible',LCA_OPENAI_BASE_URL:`http://127.0.0.1:${server.address().port}/v1`,LCA_OPENAI_MODEL:'packaged-smoke-model',LCA_OPENAI_API_KEY:'',LCA_OLLAMA_URL:'http://127.0.0.1:1',LCA_CONTEXT_RESERVED_OUTPUT_TOKENS:'1024'};
   delete env.ELECTRON_RUN_AS_NODE;
   if(process.argv.includes('--no-sdk')){env.PATH=path.join(process.env.WINDIR,'System32')+';'+process.env.WINDIR;env.Path=env.PATH;env.LCA_NO_SDK_ACCEPTANCE='1';}
   child=cp.spawn(exe,[],{cwd:output,env,windowsHide:true,stdio:['ignore','pipe','pipe']});
   const errors=[];child.stderr.on('data',d=>{if(/Error|Exception/.test(String(d)))errors.push(String(d).slice(-500));});
   const exit=await new Promise((resolve,reject)=>{const timer=setTimeout(()=>{cp.spawnSync('taskkill',['/PID',String(child.pid),'/T','/F'],{windowsHide:true,stdio:'ignore'});reject(Error('Owned packaged acceptance timeout'));},90000);child.once('error',e=>{clearTimeout(timer);reject(e);});child.once('exit',code=>{clearTimeout(timer);resolve(code);});});
   child=null;if(exit!==0||!fs.existsSync(marker))throw Error('Package exited '+exit+' before marker; '+errors.join(' '));
   const data=JSON.parse(fs.readFileSync(marker,'utf8'));if(!data.ok||!data.chat_verified||!data.file_verified||!data.packaged)throw Error('Package chat/file proof failed: '+JSON.stringify(data));
   report.runs.push({result:'PASS',exit_code:exit,...data});
  }
  if(calls<4)throw Error('No actual mock HTTP conversation');
  report.result='PASS';report.model_requests=calls;
 }catch(e){report.result='FAIL';report.error=String(e.stack||e).slice(0,2000);process.exitCode=1;}
 finally{if(child?.pid)cp.spawnSync('taskkill',['/PID',String(child.pid),'/T','/F'],{windowsHide:true,stdio:'ignore'});server.closeAllConnections();await new Promise(r=>server.close(r));fs.writeFileSync(path.join(output,'report.json'),JSON.stringify(report,null,2));console.log(JSON.stringify(report,null,2));}
})();
