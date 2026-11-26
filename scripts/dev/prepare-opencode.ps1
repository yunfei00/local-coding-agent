$ErrorActionPreference = 'Stop'
$root = (Resolve-Path (Join-Path $PSScriptRoot '../..')).Path
$lock = Get-Content (Join-Path $root 'scripts/validation/opencode/version-lock.json') -Raw | ConvertFrom-Json
$stage = Join-Path $root 'build/opencode-runtime'
$temp = Join-Path ([System.IO.Path]::GetTempPath()) ([guid]::NewGuid().ToString())
New-Item -ItemType Directory -Path $temp | Out-Null
try {
    $zip = Join-Path $temp $lock.asset
    Invoke-WebRequest -UseBasicParsing -Uri "$($lock.repository)/releases/download/$($lock.version)/$($lock.asset)" -OutFile $zip
    if ((Get-FileHash -LiteralPath $zip -Algorithm SHA256).Hash -ne $lock.archive_sha256) { throw 'OpenCode archive checksum mismatch' }
    Expand-Archive -LiteralPath $zip -DestinationPath (Join-Path $temp 'expanded')
    $bins = @(Get-ChildItem (Join-Path $temp 'expanded') -Recurse -File -Filter 'opencode.exe')
    if ($bins.Count -ne 1) { throw 'Expected exactly one OpenCode executable' }
    if ((Get-FileHash -LiteralPath $bins[0].FullName -Algorithm SHA256).Hash -ne $lock.executable_sha256) { throw 'OpenCode executable checksum mismatch' }
    $license = Join-Path $temp 'LICENSE'
    Invoke-WebRequest -UseBasicParsing -Uri "https://raw.githubusercontent.com/anomalyco/opencode/$($lock.commit)/LICENSE" -OutFile $license
    New-Item -ItemType Directory -Force -Path $stage | Out-Null
    Copy-Item -LiteralPath $bins[0].FullName -Destination (Join-Path $stage 'opencode.exe') -Force
    Copy-Item -LiteralPath $license -Destination (Join-Path $stage 'LICENSE') -Force
    Write-Host "Verified OpenCode staged: $stage"
} finally {
    Remove-Item -LiteralPath $temp -Recurse -Force
}
