const {spawn} = require('node:child_process');
const electron = require('electron');
const path = require('node:path');
const args = [path.resolve(__dirname), '--no-sandbox', '--disable-gpu'];
const env = {...process.env, ELECTRON_RUN_AS_NODE:undefined, LCA_M2_NODE:process.execPath};
const child = process.platform === 'linux' && !process.env.DISPLAY
  ? spawn('xvfb-run', ['-a', electron, ...args], {stdio:'inherit',env})
  : spawn(electron, args, {stdio:'inherit',env});
child.on('error', error => {console.error(error); process.exit(1);});
child.on('exit', code => process.exit(code ?? 1));
