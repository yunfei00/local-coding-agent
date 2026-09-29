$ErrorActionPreference = "Stop"

if ($env:OS -ne "Windows_NT") {
    throw "Windows package must be built on Windows."
}

$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
Set-Location $RepoRoot

$DesktopPackage = Get-Content ".\desktop\package.json" -Raw | ConvertFrom-Json
$RootPackage = Get-Content ".\package.json" -Raw | ConvertFrom-Json
$Version = [string]$DesktopPackage.version
if (-not $Version) {
    throw "desktop/package.json does not contain a version."
}
if ([string]$RootPackage.version -ne $Version) {
    throw "Root version $($RootPackage.version) does not match Desktop version $Version."
}

$PyProject = Get-Content ".\pyproject.toml" -Raw
$PyVersionMatch = [regex]::Match($PyProject, '(?ms)^\[project\].*?^version\s*=\s*"([^"]+)"')
if (-not $PyVersionMatch.Success -or $PyVersionMatch.Groups[1].Value -ne $Version) {
    throw "pyproject.toml version does not match Desktop version $Version."
}

$VersionPy = Get-Content ".\agent\core\version.py" -Raw
$AgentVersionMatch = [regex]::Match($VersionPy, 'APP_VERSION\s*=\s*"([^"]+)"')
if (-not $AgentVersionMatch.Success -or $AgentVersionMatch.Groups[1].Value -ne $Version) {
    throw "Agent APP_VERSION does not match Desktop version $Version."
}

Write-Host "===== Local Coding Agent v$Version Windows Package ====="
Write-Host "Repo: $RepoRoot"

if (-not (Get-Command uv -ErrorAction SilentlyContinue)) { throw "uv was not found in PATH." }
if (-not (Get-Command node -ErrorAction SilentlyContinue)) { throw "node was not found in PATH." }
if (-not (Get-Command npm -ErrorAction SilentlyContinue)) { throw "npm was not found in PATH." }

if (-not (Test-Path ".venv\Scripts\python.exe")) {
    uv venv --python 3.12 .venv
}

function Invoke-DesktopSmoke {
    param(
        [Parameter(Mandatory = $true)][string]$Executable,
        [Parameter(Mandatory = $true)][string]$Name
    )

    if (-not (Test-Path $Executable)) {
        throw "Smoke executable does not exist: $Executable"
    }

    $SmokeFile = Join-Path $RepoRoot ("build\packaged-" + $Name + "-smoke.json")
    $SmokeData = Join-Path $RepoRoot ("build\packaged-" + $Name + "-data")
    Remove-Item $SmokeFile -Force -ErrorAction SilentlyContinue
    Remove-Item $SmokeData -Recurse -Force -ErrorAction SilentlyContinue
    New-Item -ItemType Directory -Path $SmokeData -Force | Out-Null

    $BeforeAgentIds = @(Get-Process "lca-agent" -ErrorAction SilentlyContinue | ForEach-Object { $_.Id })

    $OldSmoke = $env:LCA_PACKAGED_SMOKE_FILE
    $OldData = $env:LCA_DATA_DIR
    $OldOllama = $env:LCA_OLLAMA_URL
    $env:LCA_PACKAGED_SMOKE_FILE = $SmokeFile
    $env:LCA_DATA_DIR = $SmokeData
    $env:LCA_OLLAMA_URL = "http://127.0.0.1:1"

    try {
        $DesktopProcess = Start-Process -FilePath $Executable -PassThru
        $Deadline = (Get-Date).AddSeconds(45)

        while ((Get-Date) -lt $Deadline -and -not (Test-Path $SmokeFile)) {
            $DesktopProcess.Refresh()
            if ($DesktopProcess.HasExited) { break }
            Start-Sleep -Milliseconds 250
        }

        if (-not (Test-Path $SmokeFile)) {
            throw "$Name did not connect Renderer to its bundled Agent."
        }

        $Smoke = Get-Content $SmokeFile -Raw | ConvertFrom-Json
        if (-not $Smoke.ok -or -not $Smoke.packaged -or -not $Smoke.renderer_ready -or [string]$Smoke.version -ne $Version -or -not [string]$Smoke.protocol) {
            throw "$Name smoke result was invalid: $(Get-Content $SmokeFile -Raw)"
        }

        if (-not $DesktopProcess.HasExited) {
            Wait-Process -Id $DesktopProcess.Id -Timeout 10 -ErrorAction SilentlyContinue
            $DesktopProcess.Refresh()
        }
        if (-not $DesktopProcess.HasExited) {
            Stop-Process -Id $DesktopProcess.Id -Force
            throw "$Name did not exit after smoke test."
        }
    }
    finally {
        if ($null -eq $OldSmoke) { Remove-Item Env:LCA_PACKAGED_SMOKE_FILE -ErrorAction SilentlyContinue } else { $env:LCA_PACKAGED_SMOKE_FILE = $OldSmoke }
        if ($null -eq $OldData) { Remove-Item Env:LCA_DATA_DIR -ErrorAction SilentlyContinue } else { $env:LCA_DATA_DIR = $OldData }
        if ($null -eq $OldOllama) { Remove-Item Env:LCA_OLLAMA_URL -ErrorAction SilentlyContinue } else { $env:LCA_OLLAMA_URL = $OldOllama }
    }

    Start-Sleep -Milliseconds 750
    $RemainingAgentIds = @(Get-Process "lca-agent" -ErrorAction SilentlyContinue | Where-Object { $BeforeAgentIds -notcontains $_.Id } | ForEach-Object { $_.Id })
    if ($RemainingAgentIds.Count -gt 0) {
        Stop-Process -Id $RemainingAgentIds -Force -ErrorAction SilentlyContinue
        throw "$Name left Agent process(es) running: $($RemainingAgentIds -join ', ')"
    }

    Write-Host "$Name smoke: passed"
}

Write-Host "[1/11] Install Agent packaging dependencies..."
uv pip install -e ".[packaging]"

Write-Host "[2/11] Run Agent compile + tests..."
uv run --no-project python -m compileall agent
uv run --no-project python -m unittest discover -s tests -v

Write-Host "[3/11] Build packaged Python Agent..."
Remove-Item "build\agent-dist" -Recurse -Force -ErrorAction SilentlyContinue
Remove-Item "build\pyinstaller" -Recurse -Force -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Path "build\pyinstaller" -Force | Out-Null
uv run --no-project pyinstaller --noconfirm --clean --name lca-agent --distpath build\agent-dist --workpath build\pyinstaller\work --specpath build\pyinstaller agent\launcher.py

$AgentExe = Join-Path $RepoRoot "build\agent-dist\lca-agent\lca-agent.exe"
if (-not (Test-Path $AgentExe)) { throw "Packaged Agent executable was not created: $AgentExe" }

Write-Host "[4/11] Smoke test packaged Agent..."
uv run --no-project python scripts\validation\phase9_agent_smoke.py $AgentExe

Write-Host "[5/11] Install Desktop dependencies..."
npm --prefix desktop install --no-audit --no-fund

Write-Host "[6/11] Run Desktop checks..."
npm --prefix desktop run typecheck
npm --prefix desktop run test

Write-Host "[7/11] Build NSIS installer + portable executable..."
Remove-Item "desktop\release" -Recurse -Force -ErrorAction SilentlyContinue
npm --prefix desktop run package:win

$RendererIndex = Join-Path $RepoRoot "desktop\dist\index.html"
if (-not (Test-Path $RendererIndex)) { throw "Renderer index was not created: $RendererIndex" }
$RendererHtml = Get-Content $RendererIndex -Raw
if ($RendererHtml -match '(src|href)="/assets/') { throw "Renderer build contains absolute /assets paths and will black-screen under file://." }
if ($RendererHtml -notmatch '(src|href)="\./assets/') { throw "Renderer build does not contain expected relative ./assets paths." }

$Installer = Join-Path $RepoRoot ("desktop\release\Local-Coding-Agent-" + $Version + "-x64-Setup.exe")
$Portable = Join-Path $RepoRoot ("desktop\release\Local-Coding-Agent-" + $Version + "-x64-Portable.exe")
$DesktopExe = Join-Path $RepoRoot "desktop\release\win-unpacked\LocalCodingAgent.exe"
$BundledAgent = Join-Path $RepoRoot "desktop\release\win-unpacked\resources\agent\lca-agent.exe"

foreach ($Required in @($Installer, $Portable, $DesktopExe, $BundledAgent)) {
    if (-not (Test-Path $Required)) { throw "Expected package artifact was not created: $Required" }
}

Write-Host "[8/11] Smoke test unpacked Desktop + bundled Agent..."
Invoke-DesktopSmoke -Executable $DesktopExe -Name "unpacked"

Write-Host "[9/11] Smoke test Portable executable..."
Invoke-DesktopSmoke -Executable $Portable -Name "portable"

Write-Host "[10/11] Silent-install Setup and smoke test installed executable..."
$InstallDir = Join-Path $env:TEMP "lca-rc-fresh-install"
Remove-Item $InstallDir -Recurse -Force -ErrorAction SilentlyContinue
$InstallProcess = Start-Process -FilePath $Installer -ArgumentList @("/S", "/D=$InstallDir") -PassThru -Wait
if ($InstallProcess.ExitCode -ne 0) { throw "Setup installer exited with code $($InstallProcess.ExitCode)." }

$InstalledExe = Join-Path $InstallDir "LocalCodingAgent.exe"
if (-not (Test-Path $InstalledExe)) { throw "Setup did not create expected executable: $InstalledExe" }
Invoke-DesktopSmoke -Executable $InstalledExe -Name "setup"

$Uninstaller = Get-ChildItem $InstallDir -Filter "Uninstall*.exe" -ErrorAction SilentlyContinue | Select-Object -First 1
if ($Uninstaller) {
    $UninstallProcess = Start-Process -FilePath $Uninstaller.FullName -ArgumentList "/S" -PassThru -Wait
    if ($UninstallProcess.ExitCode -ne 0) { throw "Silent uninstall exited with code $($UninstallProcess.ExitCode)." }
}
Remove-Item $InstallDir -Recurse -Force -ErrorAction SilentlyContinue

Write-Host "[11/11] Write and verify SHA256 checksums..."
$ChecksumFile = Join-Path $RepoRoot "desktop\release\SHA256SUMS.txt"
@($Installer, $Portable) | ForEach-Object {
    $Hash = Get-FileHash $_ -Algorithm SHA256
    "$($Hash.Hash.ToLowerInvariant())  $([System.IO.Path]::GetFileName($_))"
} | Set-Content -Path $ChecksumFile -Encoding ascii

$ChecksumLines = @(Get-Content $ChecksumFile | Where-Object { $_.Trim() })
if ($ChecksumLines.Count -ne 2) { throw "SHA256SUMS.txt must contain exactly Setup and Portable." }
foreach ($Line in $ChecksumLines) {
    if ($Line -notmatch '^([0-9a-f]{64})  (.+)$') { throw "Invalid checksum line: $Line" }
    $Expected = $Matches[1]
    $FileName = $Matches[2]
    $Target = Join-Path (Split-Path $ChecksumFile -Parent) $FileName
    if (-not (Test-Path $Target)) { throw "Checksum target missing: $Target" }
    $Actual = (Get-FileHash $Target -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($Actual -ne $Expected) { throw "Checksum verification failed for $FileName." }
}
Write-Host "SHA256 verification: passed"

Write-Host ""
Write-Host "Installer: $Installer"
Write-Host "Portable:  $Portable"
Write-Host "Agent:     $BundledAgent"
Write-Host "Checksums: $ChecksumFile"
Write-Host "===== WINDOWS PACKAGE BUILD PASSED ====="
