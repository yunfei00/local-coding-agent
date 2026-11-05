const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs'),os=require('node:os'),path=require('node:path');
const {readyProcessId,matchesReadyProcess,closeOwnedApplication}=require('./live_gui_guard.cjs');
test('历史 PID 文件不足以授权，必须匹配本次实际就绪输出',()=>{
 const folder=fs.mkdtempSync(path.join(os.tmpdir(),'lca-guard-')),file=path.join(folder,'process.json');
 try{fs.writeFileSync(file,JSON.stringify({pid:1234}));assert.equal(matchesReadyProcess(1234,null,file),false);assert.equal(readyProcessId('npm started'),null);assert.equal(readyProcessId('M5_ELECTRON_READY {bad}'),null);assert.equal(readyProcessId('M5_ELECTRON_READY {"pid":1234}\n'),1234);assert.equal(matchesReadyProcess(1234,1234,file),true);assert.equal(matchesReadyProcess(5678,1234,file),false);fs.writeFileSync(file,JSON.stringify({pid:5678}));assert.equal(matchesReadyProcess(1234,1234,file),false);}finally{fs.unlinkSync(file);fs.rmdirSync(folder);}
});
test('关闭后 Electron 不再暴露 process 时，仍保存正常退出码而不掩盖验收结果',async()=>{
 const child={pid:1234,exitCode:null,signalCode:null};let closed=false,killed=false;
 const app={close:async()=>{closed=true;child.exitCode=0;},process:()=>{if(closed)throw Error('application closed');return child;}};
 const retained=app.process();const result=await closeOwnedApplication(app,retained,{kill:()=>{killed=true;}});
 assert.equal(result.exit_code,0);assert.equal(result.forced,false);assert.equal(killed,false);assert.throws(()=>app.process());
});
test('关闭无响应有界，强制停止只针对已保留的自有进程',async()=>{
 const child={pid:4321,exitCode:null,signalCode:null};const killed=[];
 const result=await closeOwnedApplication({close:()=>new Promise(()=>{})},child,{timeout:5,kill:pid=>{killed.push(pid);child.exitCode=1;}});
 assert.deepEqual(killed,[4321]);assert.equal(result.exit_code,1);assert.equal(result.forced,true);
});
