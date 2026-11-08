/* Opt-in test harness. The protected key goes only to the private Python driver. */
const {app, safeStorage} = require('electron');
const {mkdtempSync, readFileSync, writeFileSync} = require('node:fs');
const {tmpdir} = require('node:os');
const path = require('node:path');
const {spawnSync} = require('node:child_process');

const savedDirectory = path.join(process.env.APPDATA, 'local-coding-agent-desktop');
const temporary = mkdtempSync(path.join(tmpdir(), 'lca-targeted-vault-'));
try {
  const localState = JSON.parse(readFileSync(path.join(savedDirectory, 'Local State'), 'utf8'));
  if (localState.os_crypt) {
    writeFileSync(path.join(temporary, 'Local State'), JSON.stringify({os_crypt: localState.os_crypt}), {mode:0o600});
  }
} catch {
  process.stderr.write('Protected Chromium state is unavailable.\n');
  app.exit(1);
}
app.setPath('userData', temporary);
app.whenReady().then(() => {
  let stage = 'os_storage';
  try {
    const args = process.argv.slice(2);
    if (!safeStorage.isEncryptionAvailable()) throw new Error('storage');
    const root = path.resolve(__dirname, '../..');
    stage = 'catalog';
    const config = spawnSync('uv', ['run','--locked','python','-m',
      'scripts.validation.targeted_kimi_benchmark','--discover'], {
      cwd:root, encoding:'utf8', windowsHide:true, timeout:30000,
    });
    if (config.status !== 0) throw new Error('configuration');
    const connection = JSON.parse(config.stdout);
    stage = 'vault';
    const {readProtectedJSON} = require(path.join(root, 'desktop/dist-electron/vaultFile.js'));
    const vault = path.join(process.env.APPDATA, 'local-coding-agent-desktop', 'model-secrets.json');
    stage = 'vault_decrypt';
    const keys = readProtectedJSON(vault, cipher => safeStorage.decryptString(cipher), 'flat');
    stage = 'configured_credential_reference';
    const secret = keys[connection.reference];
    if (!secret || !connection.url) throw new Error('credential');
    stage = 'driver';
    const result = spawnSync('uv', ['run','--locked','python','-m',
      'scripts.validation.targeted_kimi_benchmark', ...args], {
      cwd:root, stdio:'inherit', windowsHide:true, timeout:600000,
      env:{...process.env,LCA_TARGETED_KIMI_SECRET:secret,LCA_TARGETED_KIMI_ENDPOINT:connection.url},
    });
    app.exit(result.status ?? 1);
  } catch {
    process.stderr.write('Protected Kimi comparison could not start at ' + stage + '.\n');
    app.exit(1);
  }
});
