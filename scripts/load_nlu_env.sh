#!/usr/bin/env bash
# Load scripts/nlu.env into this shell. Does not write user/system env.
# Usage from repo root:  source scripts/load_nlu_env.sh
# Do not use `set -e` here: this file is meant to be sourced.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
ENV_FILE="$SCRIPT_DIR/nlu.env"
if [[ ! -f "$ENV_FILE" ]]; then
  echo "Missing NLU env file: $ENV_FILE" >&2
  return 1 2>/dev/null || exit 1
fi

while IFS= read -r line || [[ -n "$line" ]]; do
  stripped="${line#"${line%%[![:space:]]*}"}"
  stripped="${stripped%"${stripped##*[![:space:]]}"}"
  [[ -z "$stripped" || "$stripped" == \#* || "$stripped" != *=* ]] && continue
  key="${stripped%%=*}"
  value="${stripped#*=}"
  key="${key%"${key##*[![:space:]]}"}"
  key="${key#"${key%%[![:space:]]*}"}"
  value="${value#"${value%%[![:space:]]*}"}"
  value="${value%"${value##*[![:space:]]}"}"
  value="${value%\"}"
  value="${value#\"}"
  value="${value%\'}"
  value="${value#\'}"
  if [[ -n "$key" ]]; then
    export "$key=$value"
  fi
done < "$ENV_FILE"

export CHAINLIT_APP_ROOT="$(cd "$SCRIPT_DIR/../demo" && pwd)"

echo "Loaded $ENV_FILE"
echo "AGENT_NLU_ENABLED=${AGENT_NLU_ENABLED-}"
echo "AGENT_NLU_MODEL=${AGENT_NLU_MODEL-}"
echo "AGENT_NLU_HOST=${AGENT_NLU_HOST-}"
echo "AGENT_NLU_TIMEOUT=${AGENT_NLU_TIMEOUT-}"
echo "CHAINLIT_APP_ROOT=${CHAINLIT_APP_ROOT-}"
