$ErrorActionPreference = "Stop"

$fixtureRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$template = Join-Path $fixtureRoot "template"
$stamp = Get-Date -Format "yyyyMMdd-HHmmss"
$target = Join-Path $env:TEMP ("lca-phase25-git-demo-" + $stamp)

New-Item -ItemType Directory -Force -Path $target | Out-Null
Copy-Item -Path (Join-Path $template "*") -Destination $target -Recurse -Force

git -C $target init -b main
git -C $target config user.name "Local Coding Agent Phase25"
git -C $target config user.email "phase25@example.test"
git -C $target add .
git -C $target commit -m "baseline"
git -C $target branch phase25/reference

Write-Host ""
Write-Host "Phase 25 Git validation workspace created:" -ForegroundColor Green
Write-Host $target -ForegroundColor Cyan
Write-Host ""
Write-Host "Open exactly this directory in Local Coding Agent."
