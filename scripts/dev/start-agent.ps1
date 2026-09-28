$ErrorActionPreference = "Stop"

$repo = Resolve-Path (Join-Path $PSScriptRoot "..\..")
Set-Location $repo

if (Get-Command python -ErrorAction SilentlyContinue) {
    python -m agent.server.main --port 0
} elseif (Get-Command py -ErrorAction SilentlyContinue) {
    py -3 -m agent.server.main --port 0
} else {
    throw "Python 3.11+ was not found."
}
