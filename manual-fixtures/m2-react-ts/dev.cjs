const fs = require('node:fs');
(async () => {
  const {createServer} = await import('vite');
  const server = await createServer({server:{host:'127.0.0.1', port:0}, clearScreen:false});
  await server.listen();
  const data = {pid:process.pid, url:`http://127.0.0.1:${server.httpServer.address().port}`};
  fs.mkdirSync('runtime', {recursive:true});
  fs.writeFileSync('runtime/server.json', JSON.stringify(data));
  console.log('M2_READY ' + JSON.stringify(data));
  setInterval(() => console.log('M2_HEARTBEAT'), 500);
})().catch(error => {console.error(error); process.exit(1);});
