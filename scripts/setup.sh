#!/usr/bin/env bash
# First-time Unix setup: create .venv, install demo extras, prepare data, start Chainlit.
# From repo root:  bash scripts/setup.sh
# Chainlit APP_ROOT is always demo/ (demo/.chainlit/config.toml).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
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

args=(scripts/bootstrap.py --extras "$EXTRAS" --port "$PORT")
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
