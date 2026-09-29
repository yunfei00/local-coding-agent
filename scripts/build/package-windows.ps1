$ErrorActionPreference = "Stop"

if ($env:OS -ne "Windows_NT") { throw "Phase 9 Windows package must be built on Windows." }

$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
Set-Location $RepoRoot

Write-Host "===== Local Coding Agent v0.1.0 Windows Package ====="
Write-Host "Repo: $RepoRoot"

if (-not (Get-Command uv -ErrorAction SilentlyContinue)) { throw "uv was not found in PATH." }
if (-not (Get-Command node -ErrorAction SilentlyContinue)) { throw "node was not found in PATH." }
if (-not (Get-Command npm -ErrorAction SilentlyContinue)) { throw "npm was not found in PATH." }

if (-not (Test-Path ".venv\Scripts\python.exe")) { uv venv --python 3.12 .venv }

Write-Host "[1/6] Install Agent packaging dependencies..."
uv pip install -e ".[packaging]"

Write-Host "[2/6] Build packaged Python Agent..."
Remove-Item "build\agent-dist" -Recurse -Force -ErrorAction SilentlyContinue
Remove-Item "build\pyinstaller" -Recurse -Force -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Path "build\pyinstaller" -Force | Out-Null
uv run --no-project pyinstaller --noconfirm --clean --name lca-agent --distpath build\agent-dist --workpath build\pyinstaller\work --specpath build\pyinstaller agent\launcher.py

$AgentExe = Join-Path $RepoRoot "build\agent-dist\lca-agent\lca-agent.exe"
if (-not (Test-Path $AgentExe)) { throw "Packaged Agent executable was not created: $AgentExe" }

Write-Host "[3/6] Smoke test packaged Agent..."
uv run --no-project python scripts\validation\phase9_agent_smoke.py $AgentExe

Write-Host "[4/6] Install Desktop dependencies..."
npm --prefix desktop install --no-audit --no-fund

Write-Host "[5/6] Run Desktop checks..."
npm --prefix desktop run typecheck
npm --prefix desktop run test

Write-Host "[6/6] Build NSIS installer + portable executable..."
Remove-Item "desktop\release" -Recurse -Force -ErrorAction SilentlyContinue
npm --prefix desktop run package:win

$Installer = Join-Path $RepoRoot "desktop\release\Local-Coding-Agent-0.1.0-x64-Setup.exe"
$Portable = Join-Path $RepoRoot "desktop\release\Local-Coding-Agent-0.1.0-x64-Portable.exe"
$BundledAgent = Join-Path $RepoRoot "desktop\release\win-unpacked\resources\agent\lca-agent.exe"

foreach ($Required in @($Installer, $Portable, $BundledAgent)) {
    if (-not (Test-Path $Required)) { throw "Expected package artifact was not created: $Required" }
}

Write-Host ""
Write-Host "Installer: $Installer"
Write-Host "Portable:  $Portable"
Write-Host "Agent:     $BundledAgent"
Write-Host "Logs after runtime launch: %APPDATA%\local-coding-agent-desktop\logs"
Write-Host ""
Write-Host "===== PHASE 9 PACKAGE BUILD PASSED ====="
