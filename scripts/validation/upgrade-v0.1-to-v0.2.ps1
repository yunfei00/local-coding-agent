param(
    [string]$CurrentInstaller = ""
)

$ErrorActionPreference = "Stop"

$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
Set-Location $RepoRoot

$DesktopPackage = Get-Content ".\desktop\package.json" -Raw | ConvertFrom-Json
$CurrentVersion = [string]$DesktopPackage.version
if (-not $CurrentInstaller) {
    $CurrentInstaller = Join-Path $RepoRoot ("desktop\release\Local-Coding-Agent-" + $CurrentVersion + "-x64-Setup.exe")
}
$CurrentInstaller = (Resolve-Path $CurrentInstaller).Path

$OldVersion = "0.1.0"
$OldBaseUrl = "https://github.com/yunfei00/local-coding-agent/releases/download/v0.1.0"
$OldInstallerUrl = "$OldBaseUrl/Local-Coding-Agent-0.1.0-x64-Setup.exe"
$OldChecksumsUrl = "$OldBaseUrl/SHA256SUMS.txt"

$TempBase = if ($env:RUNNER_TEMP) { $env:RUNNER_TEMP } else { $env:TEMP }
$Root = Join-Path $TempBase "lca-v01-v02-upgrade"
$InstallDir = Join-Path $Root "install"
$AppDataRoot = Join-Path $Root "appdata"
$OldInstaller = Join-Path $Root "Local-Coding-Agent-0.1.0-x64-Setup.exe"
$OldChecksums = Join-Path $Root "SHA256SUMS-v0.1.0.txt"

Remove-Item $Root -Recurse -Force -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Path $Root -Force | Out-Null
New-Item -ItemType Directory -Path $AppDataRoot -Force | Out-Null

function Install-Lca {
    param(
        [Parameter(Mandatory = $true)][string]$Installer,
        [Parameter(Mandatory = $true)][string]$Target
    )
    $Process = Start-Process -FilePath $Installer -ArgumentList @("/S", "/D=$Target") -PassThru -Wait
    if ($Process.ExitCode -ne 0) {
        throw "Installer failed with exit code $($Process.ExitCode): $Installer"
    }
    $Exe = Join-Path $Target "LocalCodingAgent.exe"
    if (-not (Test-Path $Exe)) {
        throw "Installed executable missing: $Exe"
    }
    return $Exe
}

function Invoke-VersionSmoke {
    param(
        [Parameter(Mandatory = $true)][string]$Executable,
        [Parameter(Mandatory = $true)][string]$ExpectedVersion,
        [Parameter(Mandatory = $true)][string]$Name
    )

    $SmokeFile = Join-Path $Root ("smoke-" + $Name + ".json")
    Remove-Item $SmokeFile -Force -ErrorAction SilentlyContinue

    $OldSmoke = $env:LCA_PACKAGED_SMOKE_FILE
    $OldAppData = $env:APPDATA
    $OldOllama = $env:LCA_OLLAMA_URL
    $env:LCA_PACKAGED_SMOKE_FILE = $SmokeFile
    $env:APPDATA = $AppDataRoot
    $env:LCA_OLLAMA_URL = "http://127.0.0.1:1"

    try {
        $Process = Start-Process -FilePath $Executable -PassThru
        $Deadline = (Get-Date).AddSeconds(45)
        while ((Get-Date) -lt $Deadline -and -not (Test-Path $SmokeFile)) {
            $Process.Refresh()
            if ($Process.HasExited) { break }
            Start-Sleep -Milliseconds 250
        }
        if (-not (Test-Path $SmokeFile)) {
            throw "$Name did not produce packaged smoke output."
        }

        $Smoke = Get-Content $SmokeFile -Raw | ConvertFrom-Json
        if (-not $Smoke.ok -or -not $Smoke.packaged -or -not $Smoke.renderer_ready) {
            throw "$Name smoke result invalid: $(Get-Content $SmokeFile -Raw)"
        }
        if ([string]$Smoke.version -ne $ExpectedVersion) {
            throw "$Name reported version $($Smoke.version), expected $ExpectedVersion."
        }

        if (-not $Process.HasExited) {
            Wait-Process -Id $Process.Id -Timeout 10 -ErrorAction SilentlyContinue
            $Process.Refresh()
        }
        if (-not $Process.HasExited) {
            Stop-Process -Id $Process.Id -Force
            throw "$Name did not exit after smoke."
        }
    }
    finally {
        if ($null -eq $OldSmoke) { Remove-Item Env:LCA_PACKAGED_SMOKE_FILE -ErrorAction SilentlyContinue } else { $env:LCA_PACKAGED_SMOKE_FILE = $OldSmoke }
        if ($null -eq $OldAppData) { Remove-Item Env:APPDATA -ErrorAction SilentlyContinue } else { $env:APPDATA = $OldAppData }
        if ($null -eq $OldOllama) { Remove-Item Env:LCA_OLLAMA_URL -ErrorAction SilentlyContinue } else { $env:LCA_OLLAMA_URL = $OldOllama }
    }
}

Write-Host "[upgrade 1/7] Download official v0.1.0 release assets..."
Invoke-WebRequest -Uri $OldInstallerUrl -OutFile $OldInstaller
Invoke-WebRequest -Uri $OldChecksumsUrl -OutFile $OldChecksums

Write-Host "[upgrade 2/7] Verify official v0.1.0 Setup checksum..."
$ExpectedLine = Get-Content $OldChecksums | Where-Object { $_ -match 'Local-Coding-Agent-0\.1\.0-x64-Setup\.exe$' } | Select-Object -First 1
if (-not $ExpectedLine -or $ExpectedLine -notmatch '^([0-9a-fA-F]{64})\s+(.+)$') {
    throw "Unable to read v0.1.0 Setup checksum."
}
$ExpectedOldHash = $Matches[1].ToLowerInvariant()
$ActualOldHash = (Get-FileHash $OldInstaller -Algorithm SHA256).Hash.ToLowerInvariant()
if ($ExpectedOldHash -ne $ActualOldHash) {
    throw "Official v0.1.0 Setup checksum verification failed."
}

Write-Host "[upgrade 3/7] Install and launch official v0.1.0..."
$OldExe = Install-Lca -Installer $OldInstaller -Target $InstallDir
Invoke-VersionSmoke -Executable $OldExe -ExpectedVersion $OldVersion -Name "v010"

$Database = Join-Path $AppDataRoot "local-coding-agent-desktop\local-coding-agent.sqlite3"
if (-not (Test-Path $Database)) {
    throw "v0.1.0 did not create its SQLite database."
}
$env:LCA_UPGRADE_DB = $Database
try {
    uv run --no-project python -c "import os,sqlite3; c=sqlite3.connect(os.environ['LCA_UPGRADE_DB']); v=c.execute('pragma user_version').fetchone()[0]; q=c.execute('pragma quick_check').fetchone()[0]; assert v==1 and q=='ok', (v,q)"
}
finally {
    Remove-Item Env:LCA_UPGRADE_DB -ErrorAction SilentlyContinue
}

Write-Host "[upgrade 4/7] Install v$CurrentVersion over v0.1.0..."
$CurrentExe = Install-Lca -Installer $CurrentInstaller -Target $InstallDir

Write-Host "[upgrade 5/7] Launch upgraded v$CurrentVersion with existing data..."
Invoke-VersionSmoke -Executable $CurrentExe -ExpectedVersion $CurrentVersion -Name "v020"

Write-Host "[upgrade 6/7] Verify SQLite migration v1 -> v2..."
$env:LCA_UPGRADE_DB = $Database
try {
    uv run --no-project python -c "import os,sqlite3; c=sqlite3.connect(os.environ['LCA_UPGRADE_DB']); v=c.execute('pragma user_version').fetchone()[0]; q=c.execute('pragma quick_check').fetchone()[0]; assert v==2 and q=='ok', (v,q)"
}
finally {
    Remove-Item Env:LCA_UPGRADE_DB -ErrorAction SilentlyContinue
}

Write-Host "[upgrade 7/7] Cleanup..."
$Uninstaller = Get-ChildItem $InstallDir -Filter "Uninstall*.exe" -ErrorAction SilentlyContinue | Select-Object -First 1
if ($Uninstaller) {
    $Uninstall = Start-Process -FilePath $Uninstaller.FullName -ArgumentList "/S" -PassThru -Wait
    if ($Uninstall.ExitCode -ne 0) {
        throw "Uninstaller failed with exit code $($Uninstall.ExitCode)."
    }
}
Remove-Item $Root -Recurse -Force -ErrorAction SilentlyContinue

Write-Host "===== v0.1.0 -> v$CurrentVersion UPGRADE VALIDATION PASSED ====="
