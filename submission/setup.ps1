# First-time setup: create .venv, install Python extras, download catalog,
# build sidecar, auto-install Ollama if missing, pull qwen3.5:4b, warm index,
# start Chainlit. Official scoring does not run this script.
# Contest zip (this folder as cwd):
#   powershell -ExecutionPolicy Bypass -File setup.ps1
# Optional PyTorch reranker + alias rebuild:  -Extras all
# Skip NLU runtime:  -SkipOllama
# Kit checkout still uses scripts/setup.ps1, which forwards here.
# Chainlit APP_ROOT is always demo/ next to this script.

param(
    [string]$Python = "",
    [string]$Extras = "demo",
    [switch]$SkipOllama,
    [switch]$NoRun,
    [switch]$Check,
    [int]$Port = 8006,
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$BootstrapArgs = @()
)

$ErrorActionPreference = "Stop"
$Submission = $PSScriptRoot
$Parent = Split-Path -Parent $Submission
if ((Test-Path -LiteralPath (Join-Path $Parent "evaluator")) -and (Test-Path -LiteralPath (Join-Path $Parent "starter"))) {
    $Root = $Parent
} else {
    $Root = $Submission
}
Set-Location $Root

function Resolve-Python {
    param([string]$Hint)
    if ($Hint) {
        if (Test-Path -LiteralPath $Hint) {
            return (Resolve-Path -LiteralPath $Hint).Path
        }
        $found = Get-Command $Hint -ErrorAction SilentlyContinue
        if ($found) {
            return $found.Source
        }
        throw "Python executable not found: $Hint"
    }
    $py = Get-Command py -ErrorAction SilentlyContinue
    if ($py) {
        foreach ($tag in @("-3.13", "-3.12", "-3.11", "-3.10")) {
            try {
                $exe = & $py.Source $tag -c "import sys; print(sys.executable)" 2>$null
                if ($LASTEXITCODE -eq 0 -and $exe) {
                    return $exe.Trim()
                }
            } catch {
            }
        }
    }
    foreach ($name in @("python", "python3")) {
        $found = Get-Command $name -ErrorAction SilentlyContinue
        if ($found) {
            return $found.Source
        }
    }
    throw "Python 3.10+ not found. Install it from https://www.python.org/downloads/ and retry."
}

$systemPython = Resolve-Python -Hint $Python
& $systemPython -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)"
if ($LASTEXITCODE -ne 0) {
    throw "Python 3.10 or newer is required (tried $systemPython)."
}

$venvPython = Join-Path $Root ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $venvPython)) {
    Write-Host "Creating .venv with $systemPython"
    & $systemPython -m venv (Join-Path $Root ".venv")
}
if (-not (Test-Path -LiteralPath $venvPython)) {
    throw "venv python missing: $venvPython"
}

Write-Host "Using $venvPython"
& $venvPython -m pip install --upgrade pip --disable-pip-version-check

$bootstrap = Join-Path $Submission "bootstrap.py"
$flagArgs = [System.Collections.Generic.List[string]]::new()
[void]$flagArgs.Add("--extras")
[void]$flagArgs.Add($Extras)
[void]$flagArgs.Add("--port")
[void]$flagArgs.Add("$Port")
if ($Check) {
    [void]$flagArgs.Add("--check")
} elseif (-not $NoRun) {
    [void]$flagArgs.Add("--run")
    [void]$flagArgs.Add("demo")
}
if ($SkipOllama) {
    [void]$flagArgs.Add("--skip-ollama")
}
if ($BootstrapArgs) {
    foreach ($item in $BootstrapArgs) {
        [void]$flagArgs.Add($item)
    }
}

& $venvPython $bootstrap @flagArgs
exit $LASTEXITCODE
