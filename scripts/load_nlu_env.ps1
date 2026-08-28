# Load scripts/nlu.env into this PowerShell session. Does not write user/system env.
# Usage from repo root:  . .\scripts\load_nlu_env.ps1
# Then: python scripts/nlu_console.py

$ErrorActionPreference = "Stop"
$EnvFile = Join-Path $PSScriptRoot "nlu.env"
if (-not (Test-Path $EnvFile)) {
    throw "Missing NLU env file: $EnvFile"
}

Get-Content -LiteralPath $EnvFile -Encoding utf8 | ForEach-Object {
    $line = $_.Trim()
    if (-not $line -or $line.StartsWith("#") -or -not $line.Contains("=")) {
        return
    }
    $key, $value = $line.Split("=", 2)
    $key = $key.Trim()
    $value = $value.Trim().Trim("`"").Trim("'")
    if ($key) {
        Set-Item -Path "Env:$key" -Value $value
    }
}

$OllamaDir = Join-Path $env:LOCALAPPDATA "Programs\Ollama"
if (Test-Path $OllamaDir) {
    $env:PATH = "$OllamaDir;$env:PATH"
}

Write-Host "Loaded $EnvFile"
Write-Host "AGENT_NLU_ENABLED=$env:AGENT_NLU_ENABLED"
Write-Host "AGENT_NLU_MODEL=$env:AGENT_NLU_MODEL"
Write-Host "AGENT_NLU_HOST=$env:AGENT_NLU_HOST"
Write-Host "AGENT_NLU_TIMEOUT=$env:AGENT_NLU_TIMEOUT"
