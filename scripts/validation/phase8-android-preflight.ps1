param(
    [Parameter(Mandatory = $true)]
    [string]$ProjectPath
)

$ErrorActionPreference = "Stop"

$ProjectPath = (Resolve-Path $ProjectPath).Path
Set-Location $ProjectPath

Write-Host "===== Android Phase 8 Preflight ====="
Write-Host "Project: $ProjectPath"

if (-not (Test-Path ".\\gradlew.bat")) {
    throw "gradlew.bat was not found. This does not look like a Windows Gradle wrapper project."
}

if (-not (Test-Path ".\\settings.gradle") -and -not (Test-Path ".\\settings.gradle.kts")) {
    throw "settings.gradle/settings.gradle.kts was not found."
}

Write-Host "gradlew.bat: OK"
Write-Host "JAVA_HOME: $env:JAVA_HOME"

if (Get-Command java -ErrorAction SilentlyContinue) {
    java -version
} else {
    Write-Warning "java is not currently available in PATH."
}

if (Get-Command adb -ErrorAction SilentlyContinue) {
    Write-Host "adb: OK"
    adb version
} else {
    Write-Warning "adb is not currently available in PATH. Unit tests/build may still work."
}

Write-Host ""
Write-Host "Recommended Local Coding Agent validation command:"
Write-Host ".\\gradlew.bat testDebugUnitTest lintDebug assembleDebug --no-daemon --stacktrace"
