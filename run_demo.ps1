# Daily Windows launch after setup.ps1 has created .venv.
# Contest zip (this folder):  .\run_demo.ps1
# Kit checkout:  .\scripts\run_demo.ps1 (forwards here).

$ErrorActionPreference = "Stop"
$Submission = $PSScriptRoot
$Parent = Split-Path -Parent $Submission
if ((Test-Path -LiteralPath (Join-Path $Parent "evaluator")) -and (Test-Path -LiteralPath (Join-Path $Parent "starter"))) {
    $Root = $Parent
} else {
    $Root = $Submission
}
Set-Location $Root

$venvPython = Join-Path $Root ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $venvPython)) {
    Write-Host "No .venv yet; running first-time setup."
    & (Join-Path $Submission "setup.ps1") @args
    exit $LASTEXITCODE
}

& $venvPython (Join-Path $Submission "bootstrap.py") --skip-pip --run demo @args
exit $LASTEXITCODE
