// P0 security evidence without a live model. Windows-only, uses pinned OpenCode binary.
const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
const { spawn, spawnSync } = require('node:child_process');

const root = path.resolve('build/opencode-p0');
const lock = JSON.parse(fs.readFileSync(path.resolve('scripts/validation/opencode/version-lock.json'), 'utf8'));
const binary = path.join(root, 'verified-bin', 'opencode.exe');
if (process.platform !== 'win32') throw new Error('Windows only');
if (!fs.existsSync(binary)) throw new Error('Pinned OpenCode binary missing');
const hash = crypto.createHash('sha256').update(fs.readFileSync(binary)).digest('hex');
if (hash !== lock.executable_sha256) throw new Error('Binary hash mismatch');

const run = fs.mkdtempSync(path.join(root, 'security-'));
const report = { binary_hash: hash, version: lock.version, checks: [], result: 'BLOCKED' };
const out = path.join(run, 'security-evidence.json');
const pause = (ms) => new Promise(r => setTimeout(r, ms));
let child;
let baseUrl;
let password;

function rec(name, ok, detail = {}) { report.checks.push({ name, result: ok ? 'PASS' : 'FAIL', ...detail }); }

async function stopChild() {
  if (child?.pid && child.exitCode === null) {
    spawnSync(path.join(process.env.SystemRoot || 'C:\\Windows', 'System32', 'taskkill.exe'),
      ['/PID', String(child.pid), '/T', '/F'], { windowsHide: true, stdio: 'ignore', timeout: 8000 });
    for (let i = 0; i < 30 && child.exitCode === null; i++) await pause(100);
  }
  return !child?.pid || child.exitCode !== null;
}

async function main() {
  try {
    password = crypto.randomBytes(32).toString('hex');
    const config = { provider: {}, enabled_providers: [], policies: [{ action: 'provider.use', resource: '*', effect: 'deny' }] };
    const env = Object.fromEntries(Object.entries(process.env).filter(([k]) => !/key|token|secret|credential|password|^opencode_|^git_config_/i.test(k)));
    for (const k of Object.keys(env)) {
      const p = k.toLowerCase();
      if (!['systemroot','windir','path','temp','tmp','comspec','pathext','userprofile','localappdata','appdata','programfiles','programfiles(x86)'].includes(p)) delete env[k];
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
    child = spawn(binary, ['serve', '--hostname', '127.0.0.1', '--port', '0'], { cwd: run, env, windowsHide: true, stdio: ['ignore','pipe','pipe'] });
    let stdout = '';
    child.stdout.on('data', b => { stdout = (stdout + b).slice(-4000); });
    child.stderr.resume();
    const startup = Date.now() + 30000;
    while (Date.now() < startup && child.exitCode === null) {
      const m = stdout.match(/http:\/\/127\.0\.0\.1:\d+/);
      if (m) { baseUrl = m[0]; break; }
      await pause(100);
    }
    if (!baseUrl) throw new Error('SIDECAR_START_FAILED');

    const unauth = await fetch(baseUrl + '/api/info', { redirect: 'error', signal: AbortSignal.timeout(8000) });
    await unauth.body?.cancel();
    rec('unauth_401', unauth.status === 401, { httpStatus: unauth.status });

    const headers = { authorization: 'Basic ' + Buffer.from('opencode:' + password).toString('base64'), 'content-type': 'application/json' };
    const api = (route, opts = {}) => fetch(baseUrl + route, { ...opts, headers, signal: opts.signal || AbortSignal.timeout(10000) });

    const info = await api('/api/info');
    const infoBody = info.ok ? await info.json() : null;
    rec('auth_info_200', info.status === 200, { httpStatus: info.status, version: infoBody?.version });

    const bad = await api('/api/session', { method: 'POST', body: JSON.stringify({ title: 'bad', permissions: [{ action: '*', resource: '*', effect: 'allow' }] }) });
    await bad.body?.cancel();
    rec('deny_all_enforced', bad.status >= 400, { httpStatus: bad.status });

    const created = await api('/api/session', { method: 'POST', body: JSON.stringify({ title: 'p0-security', permissions: [{ action: '*', resource: '*', effect: 'deny' }] }) });
    const createdBody = created.ok ? await created.json() : null;
    const id = createdBody?.data?.id;
    rec('create_deny_all_session', created.status === 200 && !!id, { httpStatus: created.status, hasId: !!id });

    if (id) {
      const got = await api('/api/session/' + encodeURIComponent(id));
      const gotBody = got.ok ? await got.json() : null;
      rec('session_get', got.status === 200 && gotBody?.data?.id === id, { httpStatus: got.status });

      const interrupt = await api('/api/session/' + encodeURIComponent(id) + '/interrupt', { method: 'POST' });
      await interrupt.body?.cancel();
      rec('idle_interrupt', interrupt.status === 200, { httpStatus: interrupt.status });

      const active = await api('/api/session/active');
      const activeBody = active.ok ? await active.json() : null;
      const inactive = active.status === 200 && !(id in (activeBody?.data || {}));
      rec('session_inactive_after_interrupt', inactive, { httpStatus: active.status });
    }

    rec('binary_hash_pinned', true, { sha256: hash });
    report.result = report.checks.every(c => c.result === 'PASS') ? 'PASS' : 'PARTIAL';
  } catch (error) {
    report.error = String(error && error.message || error);
    report.result = 'BLOCKED';
  } finally {
    report.processReaped = await stopChild();
    if (!report.processReaped) report.result = 'BLOCKED';
    fs.writeFileSync(out, JSON.stringify(report, null, 2));
    console.log(JSON.stringify({ report: out, ...report }, null, 2));
    process.exitCode = report.result === 'PASS' ? 0 : 1;
  }
}
void main();
