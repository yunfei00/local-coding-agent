$ErrorActionPreference = "Stop"

$repo = Resolve-Path (Join-Path $PSScriptRoot "..\..")
Set-Location $repo

Write-Host "== Local Coding Agent bootstrap ==" -ForegroundColor Cyan

$required = @("git", "node", "npm", "uv")
foreach ($command in $required) {
    if (-not (Get-Command $command -ErrorAction SilentlyContinue)) {
        if ($command -eq "uv") {
            throw "uv was not found. Install uv first, then run bootstrap again."
        }
        throw "Required command not found: $command"
    }
}

Write-Host "Using uv-managed project environment..." -ForegroundColor Cyan
uv python install 3.12
uv venv --python 3.12 .venv

$venvPython = Join-Path $repo ".venv\Scripts\python.exe"
if (-not (Test-Path $venvPython)) {
    throw "Project virtual environment was not created correctly: $venvPython"
}

uv pip install --python $venvPython -e .
if ($LASTEXITCODE -ne 0) {
    throw "Unable to install Python project dependencies."
}

Write-Host "Verifying Agent runtime dependencies..." -ForegroundColor Cyan
& $venvPython -c "import sys; from importlib.metadata import version; import aiohttp, httpx2, mcp; from mcp.server import MCPServer; from mcp.types import ToolAnnotations; print('Agent Python:', sys.executable); print('mcp:', version('mcp')); print('httpx2:', version('httpx2')); print('Agent Python dependencies: OK')"
if ($LASTEXITCODE -ne 0) {
    throw "Agent Python dependency check failed after bootstrap."
}

Write-Host "Installing desktop dependencies..."
npm --prefix desktop install

Write-Host "Running backend checks with project .venv..."
& $venvPython -m compileall agent
& $venvPython -m unittest discover -s tests -v

Write-Host "Running desktop checks..."
npm --prefix desktop run typecheck
npm --prefix desktop run test

Write-Host ""
Write-Host "Bootstrap complete." -ForegroundColor Green
Write-Host "Python runtime: $venvPython"
Write-Host "Start with:"
Write-Host "  .\scripts\dev\start.ps1"
