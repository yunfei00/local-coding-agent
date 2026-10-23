const {spawn}=require('node:child_process');
const path=require('node:path');
const env={...process.env};delete env.ELECTRON_RUN_AS_NODE;
const child=spawn(require('electron'),[path.resolve(__dirname),'--disable-gpu'],{stdio:'inherit',env});
child.on('error',error=>{console.error(error);process.exit(1);});
child.on('exit',code=>process.exit(code??1));
