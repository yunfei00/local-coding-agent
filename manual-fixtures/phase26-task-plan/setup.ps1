$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$target = Join-Path $env:TEMP ("lca-phase26-plan-demo-" + (Get-Date -Format "yyyyMMdd-HHmmss"))
New-Item -ItemType Directory -Path $target -Force | Out-Null
Copy-Item -Path (Join-Path $root "src") -Destination $target -Recurse
Copy-Item -Path (Join-Path $root "tests") -Destination $target -Recurse
git -C $target init -b main
git -C $target config user.name "Local Coding Agent Phase26"
git -C $target config user.email "phase26@example.test"
git -C $target add .
git -C $target commit -m "phase26 baseline"
Write-Host "Open this disposable project in Local Coding Agent:" -ForegroundColor Green
Write-Host $target -ForegroundColor Cyan
