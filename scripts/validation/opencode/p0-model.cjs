// Windows-only real Ollama probe through the pinned OpenCode HTTP session API.
const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
const {spawn, spawnSync} = require('node:child_process');
const {createServer} = require('node:http');
const {Readable} = require('node:stream');
const {pipeline} = require('node:stream/promises');
const lock = require('./version-lock.json');

const port = Number(process.argv[2]);
const mode = process.argv[3];
if (!Number.isInteger(port) || port < 1 || port > 65535) {
  throw new Error('Supply a prevalidated local Ollama loopback port.');
}
if (mode && !['--gate-only', '--lifecycle-only', '--crash-only', '--revoke-only', '--p2'].includes(mode)) {
  throw new Error('Unknown P0 probe mode.');
}
const model = mode === '--p2' ? (process.argv[4] || 'gemma4:31b') : 'gemma4:31b';
if (!/^[a-zA-Z0-9][a-zA-Z0-9_.:/-]{0,127}$/.test(model)) throw new Error('Invalid local model ID');
if (mode === '--p2' && process.env.LCA_P2_FIXTURE_ONLY !== '1') throw new Error('Use the P2 fixture runner.');
const ollama = `http://127.0.0.1:${port}`;
const root = path.resolve('build/opencode-p0');
const binary = path.join(root, 'verified-bin', 'opencode.exe');
if (crypto.createHash('sha256').update(fs.readFileSync(binary)).digest('hex') !== lock.executable_sha256) {
  throw new Error('Fixed-version executable hash mismatch.');
}
const run = fs.mkdtempSync(path.join(root, 'model-'));
const project = path.join(run, 'project');
fs.mkdirSync(project);
const report = {version: lock.version, model, forwarded: 0, rejected: 0, cases: []};
const output = path.join(run, 'report.json');
const deadline = Date.now() + (mode === '--p2' ? 900_000 : 480_000);
const requestLimit = mode === '--p2' ? 28 : 16;
const gatewayToken = crypto.randomBytes(32).toString('hex');
let gatewayClosed = false;
let beforeForward;
let parkedRequest;
let child;
let server;
let terminalSignal;
const pause = (ms) => new Promise(resolve => setTimeout(resolve, ms));

async function gateway(incoming, outgoing) {
  const reject = (status, message) => {
    report.rejected++;
    if (!outgoing.headersSent) outgoing.writeHead(status, {'content-type': 'application/json'});
    outgoing.end(JSON.stringify({error: {message, type: 'p0_gateway'}}));
  };
  if (incoming.headers.authorization !== `Bearer ${gatewayToken}`) {
    reject(401, 'Invalid P0 gateway credentials');
    return;
  }
  if (incoming.method !== 'POST' || incoming.url !== '/v1/chat/completions') {
    reject(404, 'Only the allowlisted model route is enabled');
    return;
  }
  if (gatewayClosed || report.forwarded >= requestLimit || Date.now() >= deadline) {
    reject(403, 'P0 gateway request or time limit reached');
    return;
  }
  try {
    let length = 0;
    const chunks = [];
    for await (const chunk of incoming) {
      length += chunk.length;
      if (length > 96_000) {
        reject(413, 'P0 gateway input byte limit reached');
        return;
      }
      chunks.push(chunk);
    }
    const body = JSON.parse(Buffer.concat(chunks));
    if (body.model !== model || gatewayClosed || report.forwarded >= requestLimit || Date.now() >= deadline) {
      reject(403, 'P0 gateway model, request or time limit reached');
      return;
    }
    if (parkedRequest) {
      const pending = parkedRequest;
      parkedRequest = undefined;
      outgoing.once('close', () => pending.closed = true);
      pending.reached();
      // This request intentionally never reaches Ollama.
      setTimeout(() => { if (!outgoing.destroyed) outgoing.destroy(); }, 12_000).unref();
      return;
    }
    const prepare = beforeForward;
    beforeForward = undefined;
    if (prepare) await prepare();
    if (gatewayClosed || report.forwarded >= requestLimit || Date.now() >= deadline) {
      reject(403, 'P0 gateway request or time limit reached');
      return;
    }
    const outputLimit = Number.isInteger(body.max_tokens) && body.max_tokens > 0 ? body.max_tokens : 512;
    body.max_tokens = Math.min(outputLimit, 512);
    delete body.max_completion_tokens;
    report.forwarded++;
    const controller = new AbortController();
    outgoing.once('close', () => controller.abort());
    const response = await fetch(ollama + '/v1/chat/completions', {
      method: 'POST',
      headers: {'content-type': 'application/json'},
      body: JSON.stringify(body),
      redirect: 'error',
      signal: AbortSignal.any([
        controller.signal, AbortSignal.timeout(Math.max(1, Math.min(90_000, deadline - Date.now()))),
      ]),
    });
    report.lastModelHttpStatus = response.status;
    outgoing.writeHead(response.status, {'content-type': response.headers.get('content-type') || 'application/json'});
    if (response.body) await pipeline(Readable.fromWeb(response.body), outgoing);
    else outgoing.end();
  } catch {
    if (!outgoing.headersSent && !outgoing.destroyed) reject(502, 'Upstream request failed');
    else outgoing.destroy();
  }
}

async function start() {
  if (!server) {
    server = createServer((request, response) => void gateway(request, response));
    await new Promise((resolve, reject) => {
      server.once('error', reject);
      server.listen(0, '127.0.0.1', resolve);
    });
  }
  const config = {
    policies: [
      {action: 'provider.use', resource: '*', effect: 'deny'},
      {action: 'provider.use', resource: 'p0-ollama', effect: 'allow'},
    ],
    model: `p0-ollama/${model}`,
    providers: {
      'p0-ollama': {
        package: '@opencode/ai/providers/openai-compatible',
        settings: {baseURL: `http://127.0.0.1:${server.address().port}/v1`, apiKey: gatewayToken},
        models: {[model]: {name: model, capabilities: {tools: true}, limit: {context: 8192, output: 512}}},
      },
    },
  };
  const password = crypto.randomBytes(32).toString('hex');
  const env = Object.fromEntries(Object.entries(process.env).filter(([key]) =>
    !/key|token|secret|credential|password|^opencode_|^git_config_/i.test(key)));
  if (mode === '--p2') {
    const permitted = new Set(['systemroot','windir','path','temp','tmp','comspec','pathext']);
    for (const key of Object.keys(env)) if (!permitted.has(key.toLowerCase())) delete env[key];
    Object.assign(env, {GIT_CONFIG_NOSYSTEM:'1', GIT_CONFIG_GLOBAL:'NUL', GIT_TERMINAL_PROMPT:'0'});
  }
  Object.assign(env, {
    OPENCODE_TEST_HOME: run,
    OPENCODE_CONFIG_DIR: path.join(run, 'config'),
    XDG_CONFIG_HOME: path.join(run, 'config'),
    XDG_DATA_HOME: path.join(run, 'data'),
    XDG_CACHE_HOME: path.join(run, 'cache'),
    XDG_STATE_HOME: path.join(run, 'state'),
    OPENCODE_PASSWORD: password,
    OPENCODE_DISABLE_MODELS_FETCH: '1',
    OPENCODE_DISABLE_PROJECT_CONFIG: '1',
    OPENCODE_DISABLE_CLAUDE_CODE: '1',
    OPENCODE_CONFIG_CONTENT: JSON.stringify(config),
  });
  child = spawn(binary, ['serve', '--hostname', '127.0.0.1', '--port', '0'], {
    cwd: project, env, windowsHide: true,
  });
  let stdout = '';
  const startup = Date.now() + 30_000;
  terminalSignal = undefined;
  child.stdout.on('data', bytes => { stdout = (stdout + bytes).slice(-4000); });
  child.stderr.resume();
  child.on('error', () => { terminalSignal = 'SPAWN_ERROR'; });
  while (Date.now() < startup && child.exitCode === null && !terminalSignal) {
    const url = stdout.match(/http:\/\/127\.0\.0\.1:\d+/)?.[0];
    if (url) {
      const headers = {
        authorization: 'Basic ' + Buffer.from('opencode:' + password).toString('base64'),
        'content-type': 'application/json',
      };
      return (route, options = {}) => fetch(url + route, {
        ...options,
        headers,
        signal: options.signal || AbortSignal.timeout(10_000),
      });
    }
    await pause(100);
  }
  throw new Error('SIDECAR_START_FAILED');
}

async function stopSidecar() {
  if (child?.pid && child.exitCode === null) {
    spawnSync(path.join(process.env.SystemRoot || 'C:\\Windows','System32','taskkill.exe'), ['/PID', String(child.pid), '/T', '/F'], {windowsHide: true, stdio: 'ignore', timeout: 8000});
    for (let i = 0; i < 30 && child.exitCode === null; i++) await pause(100);
  }
  return !child?.pid || child.exitCode !== null;
}

async function testInterruptAndRestart(api, permissions) {
  const result = {name: 'interrupt_and_restart', status: 'FAIL'};
  report.cases.push(result);
  const reply = await api('/api/session', {
    method: 'POST', body: JSON.stringify({title: 'P0 cancellation fixture', permissions}),
  });
  if (!reply.ok) throw new Error('SESSION_CREATE_' + reply.status);
  const id = (await reply.json()).data.id;
  const waiting = {closed: false};
  const reached = new Promise(resolve => { waiting.reached = resolve; });
  parkedRequest = waiting;
  const baseline = report.forwarded;
  const admitted = await api(`/api/session/${id}/prompt`, {
    method: 'POST', body: JSON.stringify({text: 'Reply with the word CANCEL. Do not use tools.'}),
  });
  result.admission = admitted.status;
  result.gatewayReached = await Promise.race([reached.then(() => true), pause(10_000).then(() => false)]);
  parkedRequest = undefined;
  if (!admitted.ok || !result.gatewayReached) return;
  const stopped = await api(`/api/session/${id}/interrupt`, {method: 'POST'});
  result.interrupted = stopped.ok && (await stopped.json()).interrupted === true;
  for (let i = 0; i < 30 && !waiting.closed; i++) await pause(100);
  result.gatewayConnectionClosed = waiting.closed;
  const sessionPath = `/api/session/${id}`;
  // The service acknowledges interruption before its database write settles.
  for (let i = 0; i < 20; i++) {
    const snapshot = await api(sessionPath);
    if (snapshot.ok) result.beforeRestartOutcome = (await snapshot.json()).data.outcome;
    if (result.beforeRestartOutcome === 'interrupted') break;
    await pause(150);
  }
  if (!(await stopSidecar())) throw new Error('SIDECAR_RESTART_CLEANUP_FAILED');
  const restarted = await start();
  const stored = await restarted(sessionPath);
  const snapshot = stored.ok ? (await stored.json()).data : undefined;
  result.persistedSession = snapshot?.id === id;
  result.afterRestartOutcome = snapshot?.outcome;
  const replay = await restarted(`/api/experimental/session/${id}/log?follow=false`);
  result.replayStatus = replay.status;
  const replayLog = replay.ok ? await replay.text() : '';
  result.replayContainsInterrupt = replayLog.includes('session.execution.interrupted');
  const active = await restarted('/api/session/active');
  result.inactive = active.ok && !(id in (await active.json()).data);
  result.modelRequests = report.forwarded - baseline;
  if (result.interrupted && result.gatewayConnectionClosed && result.persistedSession &&
      result.beforeRestartOutcome === 'interrupted' && result.afterRestartOutcome === 'interrupted' &&
      result.inactive && result.modelRequests === 0) result.status = 'PASS';
}

async function testCrashRestart(api, permissions) {
  const result = {name: 'crash_restart_requires_confirmation', status: 'FAIL'};
  report.cases.push(result);
  const created = await api('/api/session', {
    method: 'POST', body: JSON.stringify({title: 'P0 crash fixture', permissions}),
  });
  if (!created.ok) throw new Error('SESSION_CREATE_' + created.status);
  const id = (await created.json()).data.id;
  const pending = {};
  const reached = new Promise(resolve => { pending.reached = resolve; });
  parkedRequest = pending;
  const admitted = await api(`/api/session/${id}/prompt`, {
    method: 'POST', body: JSON.stringify({text: 'Reply with the word CRASH. Do not use tools.'}),
  });
  result.admission = admitted.status;
  result.gatewayReached = await Promise.race([reached.then(() => true), pause(10_000).then(() => false)]);
  parkedRequest = undefined;
  if (!admitted.ok || !result.gatewayReached) return;
  result.crashed = await stopSidecar();
  if (!result.crashed) throw new Error('SIDECAR_CRASH_SIMULATION_FAILED');
  const rejectedBefore = report.rejected;
  const sentBefore = report.forwarded;
  gatewayClosed = true;
  const restarted = await start();
  const restored = await restarted(`/api/session/${id}`);
  result.persistedSession = restored.ok && (await restored.json()).data.id === id;
  for (let i = 0; i < 30 && report.rejected === rejectedBefore; i++) await pause(200);
  result.unsolicitedRequests = report.rejected - rejectedBefore;
  result.modelRequests = report.forwarded - sentBefore;
  if (result.persistedSession && result.unsolicitedRequests === 0 && result.modelRequests === 0) {
    result.status = 'PASS';
  }
}

function wasWriteDenied(event) {
  if (event.type !== 'session.tool.failed') return false;
  const {type, message = ''} = event.data.error || {};
  return (type === 'permission.rejected' && /^Permission denied: edit\b/.test(message)) ||
    /^No tool named "write" is currently available\b/.test(message);
}

async function runCase(api, name, text, permissions, check, options = {}) {
  const result = {name, modelRequests: 0, events: {}, status: 'FAIL'};
  report.cases.push(result);
  const sentBefore = report.forwarded;
  let id = options.sessionId;
  if (!id) {
    const created = await api('/api/session', {method: 'POST', body: JSON.stringify({title: name, permissions})});
    if (!created.ok) throw new Error('SESSION_CREATE_' + created.status);
    id = (await created.json()).data.id;
  } else {
    const active = await api('/api/session/active');
    if (!active.ok || id in (await active.json()).data) throw new Error('SESSION_NOT_IDLE');
  }
  result.sessionId = id;
  if (options.revoke) {
    beforeForward = async () => {
      const status = await api(`/api/session/${id}`, {
        method: 'PATCH', body: JSON.stringify({permissions: options.revoke}),
      });
      result.revocationStatus = status.status;
      if (!status.ok) {
        gatewayClosed = true;
        throw new Error('PERMISSION_UPDATE_' + status.status);
      }
    };
  }
  const signal = AbortSignal.timeout(Math.max(1, Math.min(130_000, deadline - Date.now())));
  const feed = await api('/api/event', {signal});
  if (!feed.ok) throw new Error('EVENT_STREAM_' + feed.status);
  const reader = feed.body.pipeThrough(new TextDecoderStream()).getReader();
  let collected = '';
  let answer = '';
  const parts = [];
  const tokenUsage = [];
  try {
    const accepted = await api(`/api/session/${id}/prompt`, {method: 'POST', body: JSON.stringify({text})});
    result.admission = accepted.status;
    if (!accepted.ok) throw new Error('PROMPT_ADMISSION_' + accepted.status);
    while (true) {
      const read = await reader.read();
      if (read.done) throw new Error('EVENT_STREAM_CLOSED');
      collected += read.value.replaceAll('\r\n', '\n');
      for (let split = collected.indexOf('\n\n'); split >= 0; split = collected.indexOf('\n\n')) {
        const frame = collected.slice(0, split);
        collected = collected.slice(split + 2);
        const payload = frame.split('\n').filter(line => line.startsWith('data:')).map(line => line.slice(5).trim()).join('\n');
        if (!payload) continue;
        const event = JSON.parse(payload);
        if (event.data?.sessionID !== id) continue;
        result.events[event.type] = (result.events[event.type] || 0) + 1;
        if (event.type === 'session.text.delta') answer += event.data.delta || event.data.text || '';
        if (event.type === 'session.usage.updated') tokenUsage.push(event.data.tokens);
        if (event.type.startsWith('session.tool.') && !event.type.includes('.input.')) parts.push(event);
        if (event.type === 'session.tool.failed' && event.data.error?.message) {
          const detail = event.data.error.message.replaceAll(gatewayToken, '[redacted]')
            .replace(/(bearer|basic)\s+\S+/ig, '$1 [redacted]');
          fs.appendFileSync(path.join(run, name + '-tool-errors.txt'), detail.slice(0, 1400) + '\n');
        }
        if (event.type === 'session.execution.failed' || event.type === 'session.execution.interrupted') {
          result.failure = event.data.error?.type || event.type;
          if (event.data.error?.status) result.failureHttpStatus = event.data.error.status;
          if (event.data.error?.message) {
            const detail = event.data.error.message.replaceAll(gatewayToken, '[redacted]')
              .replace(/(bearer|basic)\s+\S+/ig, '$1 [redacted]');
            fs.writeFileSync(path.join(run, name + '-error.txt'), detail.slice(0, 1800));
          }
          if (options.acceptFailedExecution && check(answer, parts)) result.status = 'PASS';
          return result;
        }
        if (event.type === 'session.execution.succeeded') {
          result.status = check(answer, parts) ? 'PASS' : 'FAIL';
          if (result.status === 'FAIL') result.failure = 'ASSERTION_FAILED';
          return result;
        }
      }
    }
  } catch (error) {
    result.failure = error.name === 'TimeoutError' ? 'TIMEOUT' : error.message;
    await api(`/api/session/${id}/interrupt`, {method: 'POST'}).catch(() => {});
    return result;
  } finally {
    beforeForward = undefined;
    await reader.cancel().catch(() => {});
    result.modelRequests = report.forwarded - sentBefore;
    result.tokenUsage = tokenUsage;
    result.toolErrors = parts.filter(event => event.type === 'session.tool.failed')
      .map(event => event.data.error?.type);
  }
}

async function main() {
  try {
    const available = await fetch(ollama + '/api/tags', {signal: AbortSignal.timeout(5000), redirect: 'error'});
    if (!available.ok || !(await available.json()).models.some(item => item.name === model)) {
      throw new Error('OLLAMA_MODEL_UNAVAILABLE');
    }
    const api = await start();
    const deny = {action: '*', resource: '*', effect: 'deny'};
    const allow = (action, resource) => ({action, resource, effect: 'allow'});
    const succeeded = (tools, n) => tools.filter(event => event.type === 'session.tool.success').length >= n;
    if (mode === '--p2') {
      report.fixtureVerified = await require('./p2-fixture.cjs').runP2Cases(api, project, runCase);
      const verifier = spawnSync('uv',['run','--locked','python','-m','scripts.validation.opencode.p2_verify',project,process.execPath],{encoding:'utf8',windowsHide:true,timeout:60000});
      report.independentVerification = {exitCode:verifier.status,passed:verifier.status===0 && !verifier.error};
      fs.writeFileSync(path.join(run,'independent-verification.json'),verifier.stdout || '');
      await testInterruptAndRestart(api,[deny]);
      report.result = report.independentVerification.passed && report.fixtureVerified && report.cases.length >= 9 && report.cases.every(item => item.status === 'PASS') ? 'PASS' : 'PARTIAL';
      return;
    }
    const marker = 'P0-' + crypto.randomBytes(5).toString('hex');
    const fixture = path.join(project, 'seed.txt');
    fs.writeFileSync(fixture, marker, 'utf8');
    if (mode === '--lifecycle-only') {
      await testInterruptAndRestart(api, [deny]);
    } else if (mode === '--crash-only') {
      await testCrashRestart(api, [deny]);
    } else if (mode !== '--gate-only' && mode !== '--revoke-only') {
      await runCase(api, 'question',
        'Answer 7 plus 8 using only its decimal numeral. Do not use tools.',
        [deny],
        (answer, tools) => answer.trim() === '15' && tools.length === 0);
      await runCase(api, 'read_and_write',
        'Read seed.txt with the read tool. Write its exact contents plus a hyphen and VERIFIED into result.txt with a file tool. Do not use the shell.',
        [deny, allow('read', 'seed.txt'), allow('edit', 'result.txt')],
        (_, tools) => succeeded(tools, 2) &&
          fs.existsSync(path.join(project, 'result.txt')) &&
          fs.readFileSync(path.join(project, 'result.txt'), 'utf8').trim() === marker + '-VERIFIED' &&
          fs.readFileSync(fixture, 'utf8') === marker);
      await runCase(api, 'shell',
        'Use the shell once to run exactly: echo P0_SHELL_CHECK\nDo not add operators or any other command. Report the observed stdout.',
        [deny, allow('shell', 'echo P0_SHELL_CHECK'), allow('shell', 'echo P0_SHELL_CHECK *')],
        (answer, tools) => succeeded(tools, 1) && answer.includes('P0_SHELL_CHECK'));
      await runCase(api, 'recover_read',
        'First use the read tool on missing.txt. When it fails, read seed.txt and answer with its exact content. Do not create any file.',
        [deny, allow('read', 'missing.txt'), allow('read', 'seed.txt')],
        (answer, tools) => tools.some(event => event.type === 'session.tool.failed') &&
          succeeded(tools, 1) && answer.trim() === marker);
    }
    if (mode === '--revoke-only' || mode === undefined) {
      const revoked = await runCase(api, 'deny_write',
        'Try using the write tool to change seed.txt to BLOCKED. Stop if denied. Do not use the shell.',
        [deny, allow('read', 'seed.txt'), allow('edit', 'seed.txt')],
        (_, tools) => fs.readFileSync(fixture, 'utf8') === marker && tools.some(wasWriteDenied),
        {acceptFailedExecution: true, revoke: [deny, allow('read', 'seed.txt')]});
      revoked.sourceUnchanged = fs.readFileSync(fixture, 'utf8') === marker;
      if (revoked.revocationStatus !== 204) revoked.status = 'FAIL';
    }
    if (mode !== '--lifecycle-only' && mode !== '--crash-only') {
      const forwardedBefore = report.forwarded;
      const rejectedBefore = report.rejected;
      gatewayClosed = true;
      const budget = await runCase(api, 'request_gate',
        'Reply with the word TEST. Do not use tools.', [deny], () => false);
      budget.status = budget.failureHttpStatus === 403 && report.forwarded === forwardedBefore &&
        report.rejected > rejectedBefore ? 'PASS' : 'FAIL';
    }
    report.result = report.cases.every(item => item.status === 'PASS') ? 'PASS' : 'PARTIAL';
  } catch (error) {
    report.result = 'BLOCKED';
    report.error = error.message;
  } finally {
    server?.close();
    server?.closeAllConnections();
    report.processReaped = await stopSidecar();
    if (!report.processReaped) report.result = 'BLOCKED';
    fs.writeFileSync(output, JSON.stringify(report, null, 2));
    console.log(JSON.stringify({report: output, ...report}, null, 2));
    process.exitCode = report.result === 'PASS' ? 0 : 1;
  }
}

void main();
