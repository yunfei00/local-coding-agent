$ErrorActionPreference = 'Stop'
$root = (Resolve-Path (Join-Path $PSScriptRoot '../..')).Path
$lock = Get-Content (Join-Path $root 'scripts/validation/opencode/version-lock.json') -Raw | ConvertFrom-Json
$stage = Join-Path $root 'build/opencode-runtime'
$temp = Join-Path ([System.IO.Path]::GetTempPath()) ([guid]::NewGuid().ToString())
function Get-ArchiveSha256([string]$File) {
    $stream = [System.IO.File]::OpenRead($File)
    $sha256 = [System.Security.Cryptography.SHA256]::Create()
    try {
        return [System.BitConverter]::ToString($sha256.ComputeHash($stream)).Replace('-', '').ToLowerInvariant()
    } finally {
        $sha256.Dispose()
        $stream.Dispose()
    }
}

$existingBinary = Join-Path $stage 'opencode.exe'
$existingLicense = Join-Path $stage 'LICENSE'
if ((Test-Path -LiteralPath $existingBinary -PathType Leaf) -and (Test-Path -LiteralPath $existingLicense -PathType Leaf) -and
    (Get-ArchiveSha256 $existingBinary) -eq $lock.executable_sha256 -and (Get-ArchiveSha256 $existingLicense) -eq $lock.license_sha256) {
    Write-Host "Verified existing OpenCode and license: $stage"
    return
}

New-Item -ItemType Directory -Path $temp | Out-Null
try {
    $zip = Join-Path $temp $lock.asset
    Invoke-WebRequest -UseBasicParsing -Uri "$($lock.repository)/releases/download/$($lock.version)/$($lock.asset)" -OutFile $zip
    if ((Get-ArchiveSha256 $zip) -ne $lock.archive_sha256) { throw 'OpenCode archive checksum mismatch' }
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    [System.IO.Compression.ZipFile]::ExtractToDirectory($zip, (Join-Path $temp 'expanded'))
    $bins = @(Get-ChildItem (Join-Path $temp 'expanded') -Recurse -File -Filter 'opencode.exe')
    if ($bins.Count -ne 1) { throw 'Expected exactly one OpenCode executable' }
    if ((Get-ArchiveSha256 $bins[0].FullName) -ne $lock.executable_sha256) { throw 'OpenCode executable checksum mismatch' }
    $license = Join-Path $temp 'LICENSE'
    Invoke-WebRequest -UseBasicParsing -Uri "https://raw.githubusercontent.com/anomalyco/opencode/$($lock.commit)/LICENSE" -OutFile $license
    if ((Get-ArchiveSha256 $license) -ne $lock.license_sha256) { throw 'OpenCode license checksum mismatch' }
    New-Item -ItemType Directory -Force -Path $stage | Out-Null
    Copy-Item -LiteralPath $bins[0].FullName -Destination (Join-Path $stage 'opencode.exe') -Force
    Copy-Item -LiteralPath $license -Destination (Join-Path $stage 'LICENSE') -Force
    Write-Host "Verified OpenCode staged: $stage"
} finally {
    Remove-Item -LiteralPath $temp -Recurse -Force
}
