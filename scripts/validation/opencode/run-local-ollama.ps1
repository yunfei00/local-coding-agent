param([ValidateSet('Chat','Write','Task')][string]$Scenario = 'Write')

$ErrorActionPreference = 'Stop'
$Root = (Resolve-Path (Join-Path $PSScriptRoot '../../..')).Path
$ReportPath = Join-Path $Root ('validation-reports\ollama-isolated-' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $ReportPath -Force | Out-Null
$Listener = [System.Net.Sockets.TcpListener]::new([System.Net.IPAddress]::Loopback, 0)
$Listener.Start()
try { $Port = $Listener.LocalEndpoint.Port } finally { $Listener.Stop() }

$Overrides = @{
    OLLAMA_HOST = "127.0.0.1:$Port"
    OLLAMA_CONTEXT_LENGTH = '8192'
    OLLAMA_NUM_PARALLEL = '1'
    OLLAMA_MAX_LOADED_MODELS = '1'
    OLLAMA_NO_CLOUD = '1'
    LCA_TEST_OLLAMA_ORIGIN = "http://127.0.0.1:$Port"
}
$Previous = @{}
$OwnedOllama = $null
$Result = 1
try {
    foreach ($Key in $Overrides.Keys) {
        $Previous[$Key] = [Environment]::GetEnvironmentVariable($Key, 'Process')
        [Environment]::SetEnvironmentVariable($Key, $Overrides[$Key], 'Process')
    }
    $Ollama = (Get-Command ollama.exe).Source
    $OwnedOllama = Start-Process -FilePath $Ollama -ArgumentList 'serve' -WindowStyle Hidden -PassThru `
        -RedirectStandardOutput (Join-Path $ReportPath 'stdout.log') -RedirectStandardError (Join-Path $ReportPath 'stderr.log')
    $Ready = $null
    foreach ($Attempt in 1..20) {
        if ($OwnedOllama.HasExited) { throw 'Isolated Ollama exited before readiness' }
        try {
            $Ready = Invoke-RestMethod "$env:LCA_TEST_OLLAMA_ORIGIN/api/tags" -TimeoutSec 2
            break
        } catch { Start-Sleep -Milliseconds 500 }
    }
    if (-not ($Ready.models | Where-Object { $_.name -eq 'qwen3:4b' -or $_.model -eq 'qwen3:4b' })) {
        throw 'The existing qwen3:4b model was not found; no download was attempted'
    }
    $ScenarioArguments = @(switch ($Scenario) { 'Write' { '--project-write' } 'Task' { '--project-task' } })
    & node (Join-Path $PSScriptRoot 'desktop-live.cjs') @ScenarioArguments
    $Result = $LASTEXITCODE
} finally {
    if ($OwnedOllama) {
        $OwnedOllama.Refresh()
        if (-not $OwnedOllama.HasExited) {
            & (Join-Path $env:WINDIR 'System32\taskkill.exe') /PID $OwnedOllama.Id /T /F | Out-Null
        }
    }
    foreach ($Key in $Previous.Keys) { [Environment]::SetEnvironmentVariable($Key, $Previous[$Key], 'Process') }
    Write-Output "Isolated runtime diagnostic directory: $ReportPath"
}
exit $Result
