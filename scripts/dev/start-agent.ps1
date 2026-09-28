$ErrorActionPreference = "Stop"

$repo = Resolve-Path (Join-Path $PSScriptRoot "..\..")
Set-Location $repo

$venvPython = Join-Path $repo ".venv\Scripts\python.exe"
if (-not (Test-Path $venvPython)) {
    throw "Project .venv was not found. Run .\scripts\dev\bootstrap.ps1 first."
}

& $venvPython -m agent.server.main --port 0
