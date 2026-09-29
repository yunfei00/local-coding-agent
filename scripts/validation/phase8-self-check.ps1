$ErrorActionPreference = "Stop"

$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\\..")).Path
Set-Location $RepoRoot

Write-Host "===== Local Coding Agent Phase 8 Self Check ====="
Write-Host "Repo: $RepoRoot"
Write-Host ""

if (-not (Get-Command uv -ErrorAction SilentlyContinue)) { throw "uv was not found in PATH." }
if (-not (Get-Command node -ErrorAction SilentlyContinue)) { throw "node was not found in PATH." }
if (-not (Get-Command npm -ErrorAction SilentlyContinue)) { throw "npm was not found in PATH." }
if (-not (Get-Command git -ErrorAction SilentlyContinue)) { throw "git was not found in PATH." }

if (-not (Test-Path ".venv\\Scripts\\python.exe") -and -not (Test-Path ".venv/bin/python")) {
    Write-Host "[1/6] Creating .venv..."
    uv venv .venv
} else {
    Write-Host "[1/6] .venv exists."
}

Write-Host "[2/6] Installing Python project..."
uv pip install -e .

Write-Host "[3/6] Python compile..."
uv run --no-project python -m compileall agent

Write-Host "[4/6] Python tests + deterministic Agent E2E..."
uv run --no-project python -m unittest discover -s tests -v

Write-Host "[5/6] Desktop typecheck + tests..."
npm --prefix desktop install --no-audit --no-fund
npm --prefix desktop run typecheck
npm --prefix desktop run test

Write-Host "[6/6] Desktop build + Git status..."
npm --prefix desktop run build
git status --short --branch

Write-Host ""
Write-Host "===== PHASE 8 SELF CHECK PASSED ====="
