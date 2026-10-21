$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
foreach ($name in @("node_modules", "build", ".venv", "target", ".gradle")) {
    $path = Join-Path $root $name
    if (Test-Path $path) {
        Remove-Item -Recurse -Force $path
    }
}

Write-Host "Phase 24 ignored-directory fixture removed." -ForegroundColor Green
