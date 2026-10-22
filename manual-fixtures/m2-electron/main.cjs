const {app} = require('electron');
const {spawn} = require('node:child_process');
const fs = require('node:fs');
const {add} = require('./math.cjs');
app.whenReady().then(() => {
  if (add(3, 2) !== 5) throw new Error('Electron fixture addition is broken');
  // Actual node.exe/python.exe descendants exercise Job / process-group cleanup.
  const node = spawn(process.env.LCA_M2_NODE, ['-e', 'setInterval(()=>{},1000)'], {stdio:'inherit'});
  const python = spawn(process.env.LCA_M2_PYTHON || 'python', ['-c', 'import time; time.sleep(300)'], {stdio:'inherit'});
  const data = {pid:process.pid, node:node.pid, python:python.pid, electron:process.versions.electron, type:process.type};
  fs.mkdirSync('runtime', {recursive:true});
  fs.writeFileSync('runtime/electron.json', JSON.stringify(data));
  console.log('M2_ELECTRON_READY ' + JSON.stringify(data));
  setInterval(() => console.log('M2_ELECTRON_HEARTBEAT'), 500);
}).catch(error => {console.error(error); app.exit(1);});
