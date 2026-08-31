#!/usr/bin/env bash
# First-time Unix setup: create .venv, install Python extras, download catalog,
# build sidecar, auto-install Ollama if missing, pull qwen3.5:4b, warm index,
# start Chainlit. Official scoring does not run this script.
# Contest zip:  bash setup.sh
# Optional extras:  EXTRAS=all bash setup.sh
# Skip NLU runtime:  SKIP_OLLAMA=1 bash setup.sh
# Kit checkout: bash scripts/setup.sh (forwards here).
set -euo pipefail

SUBMISSION="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PARENT="$(cd "$SUBMISSION/.." && pwd)"
if [[ -d "$PARENT/evaluator" && -d "$PARENT/starter" ]]; then
  ROOT="$PARENT"
else
  ROOT="$SUBMISSION"
fi
cd "$ROOT"

EXTRAS="${EXTRAS:-demo}"
PORT="${PORT:-8006}"
PYTHON_BIN="${PYTHON:-}"
NO_RUN="${NO_RUN:-0}"
CHECK="${CHECK:-0}"
SKIP_OLLAMA="${SKIP_OLLAMA:-0}"

if [[ -z "$PYTHON_BIN" ]]; then
  if command -v python3 >/dev/null 2>&1; then
    PYTHON_BIN=python3
  else
    PYTHON_BIN=python
  fi
fi

if ! "$PYTHON_BIN" -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)"; then
  echo "Python 3.10 or newer is required (tried $PYTHON_BIN)." >&2
  exit 1
fi

if [[ ! -x .venv/bin/python ]]; then
  echo "Creating .venv with $PYTHON_BIN"
  "$PYTHON_BIN" -m venv .venv
fi

.venv/bin/python -m pip install --upgrade pip --disable-pip-version-check

args=("$SUBMISSION/bootstrap.py" --extras "$EXTRAS" --port "$PORT")
if [[ "$CHECK" == "1" ]]; then
  args+=(--check)
elif [[ "$NO_RUN" != "1" ]]; then
  args+=(--run demo)
fi
if [[ "$SKIP_OLLAMA" == "1" ]]; then
  args+=(--skip-ollama)
fi
args+=("$@")

exec .venv/bin/python "${args[@]}"
