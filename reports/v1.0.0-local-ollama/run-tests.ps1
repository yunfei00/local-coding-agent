param(
    [string]$AgentExe,
    [string]$Output
)
$ErrorActionPreference = 'Stop'
$repo = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
if (-not $AgentExe) {
    $app = Get-Process LocalCodingAgent -ErrorAction SilentlyContinue | Where-Object Path | Select-Object -First 1
    if (-not $app) { throw '请启动安装版或指定 -AgentExe。' }
    $AgentExe = Join-Path (Split-Path $app.Path) 'resources\agent\lca-agent.exe'
}
$AgentExe = (Resolve-Path -LiteralPath $AgentExe).Path
if (-not $Output) { $Output = Join-Path $repo ('validation-reports\local-ollama-' + [guid]::NewGuid().ToString('N')) }
$env:PYTHONUTF8 = '1'
$env:GIT_CONFIG_GLOBAL = 'NUL'
$env:GIT_CONFIG_NOSYSTEM = '1'
Push-Location $repo
try {
    uv run --locked python scripts/validation/packaged_agent_smoke.py $AgentExe
    if ($LASTEXITCODE -ne 0) { throw '安装版后端检查失败。' }
    uv run --locked --with 'pytest==9.2.0' python -m scripts.validation.local_ollama_benchmark --agent $AgentExe --output $Output
    if ($LASTEXITCODE -ne 0) { throw '基准执行中断。' }
    $scratch = (Get-Content -LiteralPath (Join-Path $Output 'scratch-path.txt') -Raw).Trim()
    uv run --locked python -m scripts.validation.summarize_ollama_benchmark (Join-Path $Output 'results.json') $scratch (Join-Path $Output 'summary')
    if ($LASTEXITCODE -ne 0) { throw '评分汇总失败。' }
} finally {
    Pop-Location
}
