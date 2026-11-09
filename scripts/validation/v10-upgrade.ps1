param(
    [Parameter(Mandatory=$true)][string]$PreviousInstaller,
    [Parameter(Mandatory=$true)][string]$PreviousSource,
    [Parameter(Mandatory=$true)][string]$CandidateInstaller,
    [string]$PreviousVersion = '0.9.0',
    [string]$CandidateVersion = '1.0.0',
    [int]$PreviousSchema = 6,
    [switch]$KeepInstalled
)
$ErrorActionPreference='Stop'
$Repo=(Resolve-Path (Join-Path $PSScriptRoot '../..')).Path
Set-Location $Repo
foreach ($InputPath in @($PreviousInstaller,$PreviousSource,$CandidateInstaller)) {
    $Resolved=(Resolve-Path -LiteralPath $InputPath).Path
    if (-not ($Resolved.StartsWith((Join-Path $Repo 'build')+'\',[StringComparison]::OrdinalIgnoreCase) -or $Resolved.StartsWith((Join-Path $Repo 'desktop\release')+'\',[StringComparison]::OrdinalIgnoreCase))) { throw 'Only owned repository build artifacts may be installed.' }
}
$Existing=@('HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\*','HKLM:\Software\Microsoft\Windows\CurrentVersion\Uninstall\*') | ForEach-Object { Get-ItemProperty $_ -ErrorAction SilentlyContinue } | Where-Object { $_.DisplayName -match '^Local\s*Coding\s*Agent(?:\s|$)' }
if ($Existing) { throw 'Existing installation preserved; upgrade acceptance requires no existing registered product.' }
$Output=Join-Path $Repo ('build\v10-upgrade-'+[guid]::NewGuid().ToString('N'))
$Install=Join-Path $Output '安装目录 含空格'
$Data=Join-Path $Output 'data'
New-Item -ItemType Directory -Path (Join-Path $Data 'desktop') -Force | Out-Null
$Saved=@{}
foreach ($Key in @('LCA_DATA_DIR','LCA_DESKTOP_DATA_DIR','LCA_PACKAGED_SMOKE_FILE','LCA_HEADLESS_SMOKE','LCA_OLLAMA_URL','ELECTRON_RUN_AS_NODE')) { $Saved[$Key]=[Environment]::GetEnvironmentVariable($Key,'Process') }
$env:LCA_DATA_DIR=$Data;$env:LCA_DESKTOP_DATA_DIR=Join-Path $Data 'desktop';$env:LCA_HEADLESS_SMOKE='1';$env:LCA_OLLAMA_URL='http://127.0.0.1:1'
Remove-Item Env:ELECTRON_RUN_AS_NODE -ErrorAction SilentlyContinue
function Invoke-Installed([string]$Label,[string]$Version) {
    $Marker=Join-Path $Output ($Label+'.json');$env:LCA_PACKAGED_SMOKE_FILE=$Marker
    $Process=Start-Process -FilePath (Join-Path $Install 'LocalCodingAgent.exe') -PassThru -WindowStyle Hidden
    $Deadline=(Get-Date).AddSeconds(60)
    while (-not (Test-Path $Marker) -and (Get-Date) -lt $Deadline) { $Process.Refresh();if ($Process.HasExited) { break };Start-Sleep -Milliseconds 250 }
    if (-not (Test-Path $Marker)) { throw "$Label did not produce installed renderer/backend evidence." }
    $Result=Get-Content $Marker -Raw | ConvertFrom-Json
    if (-not $Result.ok -or -not $Result.packaged -or $Result.version -ne $Version) { throw "$Label installed version/readiness failed." }
    $Process.Refresh();if (-not $Process.HasExited) { Wait-Process -Id $Process.Id -Timeout 15 -ErrorAction Stop }
}
try {
    $Old=Start-Process -FilePath $PreviousInstaller -ArgumentList @('/S',"/D=$Install") -Wait -PassThru -WindowStyle Hidden
    if ($Old.ExitCode -ne 0) { throw "Previous installer exit=$($Old.ExitCode)" }
    Invoke-Installed 'previous-installed' $PreviousVersion
    & uv run --locked python scripts/validation/v10_upgrade_profile.py seed --source $PreviousSource --data $Data --previous-schema $PreviousSchema
    if ($LASTEXITCODE -ne 0) { throw 'Old schema fixture failed; no upgrade PASS.' }
    $New=Start-Process -FilePath $CandidateInstaller -ArgumentList @('/S',"/D=$Install") -Wait -PassThru -WindowStyle Hidden
    if ($New.ExitCode -ne 0) { throw "Candidate installer exit=$($New.ExitCode)" }
    Invoke-Installed 'candidate-upgraded' $CandidateVersion
    $Verification=& uv run --locked python scripts/validation/v10_upgrade_profile.py verify --source $Repo --data $Data --previous-schema $PreviousSchema
    if ($LASTEXITCODE -ne 0) { throw 'Upgrade data contract failed.' }
    $Result=$Verification | ConvertFrom-Json
    if (-not $KeepInstalled) {
        $Uninstaller=Get-ChildItem -LiteralPath $Install -Filter 'Uninstall*.exe' | Select-Object -First 1
        if (-not $Uninstaller) { throw 'Installed uninstaller missing.' }
        $Removed=Start-Process -FilePath $Uninstaller.FullName -ArgumentList '/S' -Wait -PassThru -WindowStyle Hidden
        if ($Removed.ExitCode -ne 0 -or -not (Test-Path (Join-Path $Data 'upgrade-contract.json'))) { throw 'Uninstall failed or isolated history was deleted.' }
    }
    @{result='PASS';source_version=$PreviousVersion;target_version=$CandidateVersion;data=$Result;installed_executable=(Join-Path $Install 'LocalCodingAgent.exe');kept_installed=[bool]$KeepInstalled;candidate_sha256=(Get-FileHash $CandidateInstaller -Algorithm SHA256).Hash.ToLowerInvariant();clean_os=$false} | ConvertTo-Json -Depth 8 | Set-Content (Join-Path $Output 'report.json')
    Write-Host "Upgrade evidence: $Output"
} finally {
    foreach ($Key in $Saved.Keys) {
        if ($null -eq $Saved[$Key]) { Remove-Item -LiteralPath "Env:$Key" -ErrorAction SilentlyContinue }
        else { [Environment]::SetEnvironmentVariable($Key,$Saved[$Key],'Process') }
    }
}
