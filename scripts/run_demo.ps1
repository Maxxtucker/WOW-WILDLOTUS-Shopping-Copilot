# Daily Windows launch after scripts/setup.ps1 has created .venv.
# From repo root:  .\scripts\run_demo.ps1
# Extra args are forwarded to scripts/bootstrap.py (e.g. --port 8010 --skip-ollama).
#
# Always uses .venv (not Anaconda base). bootstrap.py sets cwd=demo and
# CHAINLIT_APP_ROOT=demo so demo/.chainlit/config.toml and demo/public/ load.
# Do not run `chainlit` from the repository root.

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

$venvPython = Join-Path $Root ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $venvPython)) {
    Write-Host "No .venv yet; running first-time setup."
    & (Join-Path $PSScriptRoot "setup.ps1") @args
    exit $LASTEXITCODE
}

& $venvPython (Join-Path $PSScriptRoot "bootstrap.py") --skip-pip --run demo @args
exit $LASTEXITCODE
