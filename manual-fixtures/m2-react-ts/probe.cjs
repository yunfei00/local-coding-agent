const fs = require('node:fs');
(async () => {
  const {url} = JSON.parse(fs.readFileSync('runtime/server.json','utf8'));
  for (const path of ['/', '/src/App.tsx']) {
    const response = await fetch(url + path);
    const text = await response.text();
    if (!response.ok || !text.includes(path === '/' ? 'M2 React fixture' : 'Calculator')) throw new Error('Development server probe failed');
  }
  console.log('M2_HTTP_OK');
})().catch(error => {console.error(error); process.exit(1);});
