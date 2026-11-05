/* No window/renderer. OS-protected credentials go only to an owned stdin pipe. */
const {app,safeStorage}=require('electron');
const fs=require('node:fs'),path=require('node:path'),os=require('node:os'),cp=require('node:child_process');
const manifest=JSON.parse(fs.readFileSync(process.argv[2],'utf8'));
const protectedDirectory=fs.mkdtempSync(path.join(os.tmpdir(),'lca-v09-runtime-secure-'));
for(const name of ['Local State','model-secrets.json','provider-secrets.json']){
  const source=path.join(manifest.credential_data,name);
  if(fs.existsSync(source))fs.copyFileSync(source,path.join(protectedDirectory,name));
}
app.setPath('userData',protectedDirectory);
app.commandLine.appendSwitch('disable-gpu');
app.whenReady().then(()=>{
  if(!safeStorage.isEncryptionAvailable())throw Error('OS_SECRET_STORAGE_UNAVAILABLE');
  let credentials={};
  const source=path.join(protectedDirectory,'model-secrets.json');
  if(fs.existsSync(source)){
    const encrypted=JSON.parse(fs.readFileSync(source,'utf8')).encrypted;
    credentials=JSON.parse(safeStorage.decryptString(Buffer.from(encrypted,'base64')));
  }
  const child=cp.spawn('uv',['run','--locked','python','scripts/validation/runtime_live.py',process.argv[2]],{
    cwd:manifest.root,windowsHide:true,stdio:['pipe','inherit','inherit'],
    env:{...process.env,PYTHONUTF8:'1',LCA_DATA_DIR:manifest.data,LCA_OPENAI_API_KEY:''}
  });
  child.on('error',()=>app.exit(1));
  child.on('exit',async code=>{
    if(code)return app.exit(code);
    try{
      const report=JSON.parse(fs.readFileSync(manifest.report,'utf8'));
      const result=report.cases?.some(c=>c.name==='workflow-react'&&c.result==='PASS')?await require('./react_dom_contract.cjs').checkReact(manifest.report):0;
      app.exit(result);
    }catch{process.stderr.write('Independent DOM verification unavailable.\n');app.exit(1);}
  });
  child.stdin.end(JSON.stringify({credentials})+'\n');
  credentials={};
}).catch(()=>{process.stderr.write('Protected runtime bootstrap unavailable; no secret was printed.\n');app.exit(1);});
