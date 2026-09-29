$ErrorActionPreference = "Continue"

$repo = Resolve-Path (Join-Path $PSScriptRoot "..\..")
Set-Location $repo

Write-Host "== Local Coding Agent environment ==" -ForegroundColor Cyan

$commands = @(
    @{ Name = "git"; Args = @("--version") },
    @{ Name = "node"; Args = @("--version") },
    @{ Name = "npm"; Args = @("--version") },
    @{ Name = "python"; Args = @("--version") },
    @{ Name = "uv"; Args = @("--version") },
    @{ Name = "ollama"; Args = @("--version") }
)

foreach ($item in $commands) {
    $cmd = Get-Command $item.Name -ErrorAction SilentlyContinue
    if ($cmd) {
        Write-Host ("[OK] {0}: " -f $item.Name) -NoNewline -ForegroundColor Green
        & $item.Name @($item.Args)
    } else {
        Write-Host ("[--] {0}: not found" -f $item.Name) -ForegroundColor DarkYellow
    }
}

$venvPython = Join-Path $repo ".venv\Scripts\python.exe"
if (Test-Path $venvPython) {
    Write-Host "[OK] project .venv: " -NoNewline -ForegroundColor Green
    & $venvPython --version
    Write-Host "     $venvPython"
} else {
    Write-Host "[--] project .venv: not created yet" -ForegroundColor DarkYellow
}

Write-Host ""
Write-Host "The Agent must run from the project .venv."
Write-Host "System Python is informational only and is not used to launch the Agent."
