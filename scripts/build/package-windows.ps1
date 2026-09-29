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

Write-Host "[1/8] Install Agent packaging dependencies..."
uv pip install -e ".[packaging]"

Write-Host "[2/8] Build packaged Python Agent..."
Remove-Item "build\agent-dist" -Recurse -Force -ErrorAction SilentlyContinue
Remove-Item "build\pyinstaller" -Recurse -Force -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Path "build\pyinstaller" -Force | Out-Null
uv run --no-project pyinstaller --noconfirm --clean --name lca-agent --distpath build\agent-dist --workpath build\pyinstaller\work --specpath build\pyinstaller agent\launcher.py

$AgentExe = Join-Path $RepoRoot "build\agent-dist\lca-agent\lca-agent.exe"
if (-not (Test-Path $AgentExe)) { throw "Packaged Agent executable was not created: $AgentExe" }

Write-Host "[3/8] Smoke test packaged Agent..."
uv run --no-project python scripts\validation\phase9_agent_smoke.py $AgentExe

Write-Host "[4/8] Install Desktop dependencies..."
npm --prefix desktop install --no-audit --no-fund

Write-Host "[5/8] Run Desktop checks..."
npm --prefix desktop run typecheck
npm --prefix desktop run test

Write-Host "[6/8] Build NSIS installer + portable executable..."
Remove-Item "desktop\release" -Recurse -Force -ErrorAction SilentlyContinue
npm --prefix desktop run package:win

$Installer = Join-Path $RepoRoot "desktop\release\Local-Coding-Agent-0.1.0-x64-Setup.exe"
$Portable = Join-Path $RepoRoot "desktop\release\Local-Coding-Agent-0.1.0-x64-Portable.exe"
$BundledAgent = Join-Path $RepoRoot "desktop\release\win-unpacked\resources\agent\lca-agent.exe"

foreach ($Required in @($Installer, $Portable, $BundledAgent)) {
    if (-not (Test-Path $Required)) { throw "Expected package artifact was not created: $Required" }
}

Write-Host "[7/8] Smoke test packaged Desktop + bundled Agent..."
$DesktopExe = Join-Path $RepoRoot "desktop\release\win-unpacked\LocalCodingAgent.exe"
$SmokeFile = Join-Path $RepoRoot "build\phase9-desktop-smoke.json"
Remove-Item $SmokeFile -Force -ErrorAction SilentlyContinue

$BeforeAgentIds = @(
    Get-Process "lca-agent" -ErrorAction SilentlyContinue |
        ForEach-Object { $_.Id }
)

$env:LCA_PACKAGED_SMOKE_FILE = $SmokeFile
try {
    $DesktopProcess = Start-Process -FilePath $DesktopExe -PassThru
    $Deadline = (Get-Date).AddSeconds(30)

    while ((Get-Date) -lt $Deadline -and -not (Test-Path $SmokeFile)) {
        $DesktopProcess.Refresh()
        if ($DesktopProcess.HasExited) { break }
        Start-Sleep -Milliseconds 250
    }

    if (-not (Test-Path $SmokeFile)) {
        throw "Packaged Desktop did not connect to its bundled Agent."
    }

    $Smoke = Get-Content $SmokeFile -Raw | ConvertFrom-Json
    if (-not $Smoke.ok -or -not $Smoke.packaged -or $Smoke.protocol -ne "phase9") {
        throw "Packaged Desktop smoke result was invalid: $(Get-Content $SmokeFile -Raw)"
    }

    if (-not $DesktopProcess.HasExited) {
        Wait-Process -Id $DesktopProcess.Id -Timeout 10 -ErrorAction SilentlyContinue
        $DesktopProcess.Refresh()
    }
    if (-not $DesktopProcess.HasExited) {
        Stop-Process -Id $DesktopProcess.Id -Force
        throw "Packaged Desktop did not exit after smoke test."
    }
}
finally {
    Remove-Item Env:LCA_PACKAGED_SMOKE_FILE -ErrorAction SilentlyContinue
}

Start-Sleep -Milliseconds 750
$RemainingAgentIds = @(
    Get-Process "lca-agent" -ErrorAction SilentlyContinue |
        Where-Object { $BeforeAgentIds -notcontains $_.Id } |
        ForEach-Object { $_.Id }
)
if ($RemainingAgentIds.Count -gt 0) {
    Stop-Process -Id $RemainingAgentIds -Force -ErrorAction SilentlyContinue
    throw "Packaged Desktop left Agent process(es) running: $($RemainingAgentIds -join ', ')"
}

Write-Host "[8/8] Write SHA256 checksums..."
$ChecksumFile = Join-Path $RepoRoot "desktop\release\SHA256SUMS.txt"
@($Installer, $Portable) |
    ForEach-Object {
        $Hash = Get-FileHash $_ -Algorithm SHA256
        "$($Hash.Hash.ToLowerInvariant())  $([System.IO.Path]::GetFileName($_))"
    } |
    Set-Content -Path $ChecksumFile -Encoding ascii

Write-Host ""
Write-Host "Installer: $Installer"
Write-Host "Portable:  $Portable"
Write-Host "Agent:     $BundledAgent"
Write-Host "Checksums: $ChecksumFile"
Write-Host "Logs after runtime launch: %APPDATA%\local-coding-agent-desktop\logs"
Write-Host ""
Write-Host "===== PHASE 9 PACKAGE BUILD PASSED ====="
