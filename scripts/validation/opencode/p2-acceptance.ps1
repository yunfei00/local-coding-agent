param([int]$Port=11434,[string]$Model='gemma4:31b',[switch]$StaticOnly)
$ErrorActionPreference='Stop'
Set-Location (Resolve-Path "$PSScriptRoot/../../..")
function Check { if ($LASTEXITCODE -ne 0) { throw "Native command failed: $LASTEXITCODE" } }
git rev-parse HEAD; Check
uv sync --locked; Check
$env:LCA_TEST_PYTHON = (uv run python -c "import sys; print(sys.executable)"); Check
npm ci --prefix desktop; Check
npm run agent:check; Check
npm run agent:test; Check
npm run desktop:typecheck; Check
npm run desktop:test; Check
npm run desktop:build; Check
node scripts/validation/desktop-smoke.cjs; Check
node --test scripts/validation/opencode/p2-fixture.test.cjs; Check
if ($StaticOnly) { Write-Host 'Static checks PASS; model and UI acceptance NOT_RUN'; exit 0 }
$exe='build/opencode-p0/verified-bin/opencode.exe'
if (!(Test-Path $exe)) { throw 'Pinned OpenCode EXE missing' }
if ((Get-FileHash $exe -Algorithm SHA256).Hash.ToLower() -ne '98cb0aa854c7c015cf6febafa7afb872c359bfe5a823a526f3b4fd347a9e9677') { throw 'EXE hash mismatch' }
$env:LCA_DATA_DIR=Join-Path ([System.IO.Path]::GetTempPath()) ('lca-p2-'+[guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $env:LCA_DATA_DIR | Out-Null
Write-Host "Evidence directory: $env:LCA_DATA_DIR"
node scripts/validation/opencode/p2-runner.cjs $Port $Model; Check
Write-Host 'CLI acceptance PASS; manual UI and production gates remain separate'
