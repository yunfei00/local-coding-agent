$ErrorActionPreference = "Continue"

Write-Host "== Local Coding Agent environment ==" -ForegroundColor Cyan

$commands = @(
    @{ Name = "git"; Args = @("--version") },
    @{ Name = "node"; Args = @("--version") },
    @{ Name = "npm"; Args = @("--version") },
    @{ Name = "python"; Args = @("--version") },
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

Write-Host ""
Write-Host "Phase 0 requires Git, Node.js/npm and Python 3.11+."
Write-Host "Ollama becomes required in Phase 2."
