#!/usr/bin/env bash
# Daily Unix launch after scripts/setup.sh has created .venv.
# From repo root:  bash scripts/run_demo.sh
# Uses .venv and CHAINLIT_APP_ROOT=demo (demo/.chainlit/config.toml).
# Do not run `chainlit` from the repository root.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

if [[ ! -x .venv/bin/python ]]; then
  echo "No .venv yet; running first-time setup."
  exec bash "$ROOT/scripts/setup.sh" "$@"
fi

exec .venv/bin/python scripts/bootstrap.py --skip-pip --run demo "$@"
