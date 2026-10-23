const {app,BrowserWindow,ipcMain,screen}=require('electron');
const fs=require('node:fs');
const path=require('node:path');
const runtime=path.join(__dirname,'.runtime');
fs.mkdirSync(runtime,{recursive:true});
app.setPath('userData',path.join(runtime,'profile'));
app.commandLine.appendSwitch('force-renderer-accessibility');
const savedFile=path.join(runtime,'saved.json');
ipcMain.handle('fixture:load',()=>fs.existsSync(savedFile)?JSON.parse(fs.readFileSync(savedFile,'utf8')).value:'');
ipcMain.handle('fixture:save',(_event,value)=>{
  if(typeof value!=='string'||value.length>120) throw new Error('Invalid display name');
  fs.writeFileSync(savedFile,JSON.stringify({value}));return value;
});
app.whenReady().then(async()=>{
  const area=screen.getPrimaryDisplay().workArea;
  const window=new BrowserWindow({x:area.x+30,y:area.y+30,width:Math.min(760,area.width-60),height:Math.min(520,area.height-60),
    title:'M5 Electron acceptance',alwaysOnTop:true,
    webPreferences:{preload:path.join(__dirname,'preload.cjs'),contextIsolation:true,nodeIntegration:false,sandbox:true}});
  window.webContents.setWindowOpenHandler(()=>({action:'deny'}));
  window.webContents.on('will-navigate',event=>event.preventDefault());
  await window.loadFile(path.join(__dirname,'dist/index.html'));
  window.show();window.focus();
  const state={pid:process.pid,type:process.type,electron:process.versions.electron,
    children:app.getAppMetrics().map(metric=>metric.pid).filter(pid=>pid!==process.pid)};
  fs.writeFileSync(path.join(runtime,'process.json'),JSON.stringify(state));
  console.log('M5_ELECTRON_READY '+JSON.stringify(state));
}).catch(error=>{console.error(error);app.exit(1);});
app.on('window-all-closed',()=>app.quit());
