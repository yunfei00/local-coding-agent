$ErrorActionPreference = "Stop"

$repo = Resolve-Path (Join-Path $PSScriptRoot "..\..")
Set-Location $repo

if (-not (Test-Path "desktop\node_modules")) {
    Write-Host "desktop/node_modules is missing. Running bootstrap first..." -ForegroundColor Yellow
    & (Join-Path $PSScriptRoot "bootstrap.ps1")
}

npm run dev
