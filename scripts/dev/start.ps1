$ErrorActionPreference = "Stop"

$repo = Resolve-Path (Join-Path $PSScriptRoot "..\..")
Set-Location $repo

if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    throw "uv was not found. Install uv first, then run start again."
}

$venvPython = Join-Path $repo ".venv\Scripts\python.exe"
if (-not (Test-Path $venvPython)) {
    Write-Host ".venv is missing. Running bootstrap first..." -ForegroundColor Yellow
    & (Join-Path $PSScriptRoot "bootstrap.ps1")
}
elseif (-not (Test-Path "desktop\node_modules")) {
    Write-Host "desktop/node_modules is missing. Running bootstrap first..." -ForegroundColor Yellow
    & (Join-Path $PSScriptRoot "bootstrap.ps1")
}
else {
    Write-Host "Syncing Python project dependencies into .venv..." -ForegroundColor Cyan
    uv pip install --python $venvPython -e .
    if ($LASTEXITCODE -ne 0) {
        throw "Unable to sync Python dependencies into .venv."
    }
}

Write-Host "Verifying Agent runtime dependencies..." -ForegroundColor Cyan
& $venvPython -c "import sys; from importlib.metadata import version; import aiohttp, httpx2, mcp; from mcp.server import MCPServer; from mcp.types import ToolAnnotations; print('Agent Python:', sys.executable); print('mcp:', version('mcp')); print('httpx2:', version('httpx2')); print('Agent Python dependencies: OK')"if ($LASTEXITCODE -ne 0) {
    throw "Agent Python dependency check failed. Run .\scripts\dev\bootstrap.ps1."
}

npm run dev
