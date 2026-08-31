# First-time Windows setup: create .venv, install demo extras, prepare data, start Chainlit.
# From repo root:
#   powershell -ExecutionPolicy Bypass -File scripts/setup.ps1
# Later launches:
#   .\scripts\run_demo.ps1
# Chainlit APP_ROOT is always demo/ (demo/.chainlit/config.toml).

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
$Root = Split-Path -Parent $PSScriptRoot
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

$bootstrap = Join-Path $Root "scripts\bootstrap.py"
# Do not put the script path inside a splatted array. Windows Python (venv
# launcher / Store stub) then receives the path twice and argparse fails with
# "unrecognized arguments: ...\bootstrap.py".
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
