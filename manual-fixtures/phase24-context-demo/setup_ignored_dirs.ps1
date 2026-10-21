$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $MyInvocation.MyCommand.Path

$targets = @(
    @{ Path = "node_modules\ignored.js"; Content = "export const SHOULD_NOT_BE_INDEXED = true;" },
    @{ Path = "build\ignored.cpp"; Content = "int should_not_be_indexed() { return 0; }" },
    @{ Path = ".venv\ignored.py"; Content = "SHOULD_NOT_BE_INDEXED = True" },
    @{ Path = "target\ignored.java"; Content = "class IgnoredTarget {}" },
    @{ Path = ".gradle\ignored.kt"; Content = "class IgnoredGradle" }
)

foreach ($target in $targets) {
    $fullPath = Join-Path $root $target.Path
    $directory = Split-Path -Parent $fullPath
    New-Item -ItemType Directory -Force -Path $directory | Out-Null
    Set-Content -Path $fullPath -Value $target.Content -Encoding UTF8
}

Write-Host "Phase 24 ignored-directory fixture created." -ForegroundColor Green
Write-Host "Workspace: $root"
