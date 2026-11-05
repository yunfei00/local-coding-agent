const {app,BrowserWindow,ipcMain}=require('electron');
const fs=require('node:fs'),path=require('node:path');
const runtime=path.join(__dirname,'.runtime');fs.mkdirSync(runtime,{recursive:true});
app.setPath('userData',path.join(runtime,'profile'));app.commandLine.appendSwitch('force-renderer-accessibility');
ipcMain.handle('v07:verified',()=>{fs.writeFileSync(path.join(runtime,'result.json'),JSON.stringify({verified:true}));return true;});
ipcMain.handle('v07:pointer',(_event,data)=>{fs.writeFileSync(path.join(runtime,'pointer.json'),JSON.stringify(data));return true;});
app.whenReady().then(async()=>{
 const win=new BrowserWindow({width:980,height:720,title:'V07 Canvas acceptance',webPreferences:{preload:path.join(__dirname,'preload.cjs'),contextIsolation:true,sandbox:true,nodeIntegration:false}});
 win.webContents.setWindowOpenHandler(()=>({action:'deny'}));win.webContents.on('will-navigate',e=>e.preventDefault());
 await win.loadFile(path.join(__dirname,'index.html'));win.show();win.focus();
 const state={pid:process.pid};fs.writeFileSync(path.join(runtime,'process.json'),JSON.stringify(state));console.log('M5_ELECTRON_READY '+JSON.stringify(state));
}).catch(()=>app.exit(1));
app.on('window-all-closed',()=>app.quit());
