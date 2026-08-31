#!/usr/bin/env bash
# Daily Unix launch after setup.sh has created .venv.
# Contest zip:  bash run_demo.sh
# Kit checkout: bash scripts/run_demo.sh (forwards here).
set -euo pipefail

SUBMISSION="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PARENT="$(cd "$SUBMISSION/.." && pwd)"
if [[ -d "$PARENT/evaluator" && -d "$PARENT/starter" ]]; then
  ROOT="$PARENT"
else
  ROOT="$SUBMISSION"
fi
cd "$ROOT"

if [[ ! -x .venv/bin/python ]]; then
  echo "No .venv yet; running first-time setup."
  exec bash "$SUBMISSION/setup.sh" "$@"
fi

exec .venv/bin/python "$SUBMISSION/bootstrap.py" --skip-pip --run demo "$@"
