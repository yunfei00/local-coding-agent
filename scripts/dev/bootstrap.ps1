$ErrorActionPreference = "Stop"

$repo = Resolve-Path (Join-Path $PSScriptRoot "..\..")
Set-Location $repo

Write-Host "== Local Coding Agent bootstrap ==" -ForegroundColor Cyan

$required = @("git", "node", "npm")
foreach ($command in $required) {
    if (-not (Get-Command $command -ErrorAction SilentlyContinue)) {
        throw "Required command not found: $command"
    }
}

$python = Get-Command python -ErrorAction SilentlyContinue
if (-not $python) {
    $py = Get-Command py -ErrorAction SilentlyContinue
    if (-not $py) {
        throw "Python 3.11+ was not found. Install Python and retry."
    }
}

Write-Host "Installing Python Agent dependencies..."
if ($python) {
    python -m pip install -e .
} else {
    py -3 -m pip install -e .
}

Write-Host "Installing desktop dependencies..."
npm --prefix desktop install

Write-Host "Running backend checks..."
if ($python) {
    python -m compileall agent
    python -m unittest discover -s tests -v
} else {
    py -3 -m compileall agent
    py -3 -m unittest discover -s tests -v
}

Write-Host "Running desktop checks..."
npm --prefix desktop run typecheck
npm --prefix desktop run test

Write-Host ""
Write-Host "Bootstrap complete. Start with:" -ForegroundColor Green
Write-Host "  .\scripts\dev\start.ps1"
