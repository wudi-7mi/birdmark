#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")"

if [[ -f ".env" ]]; then
  while IFS='=' read -r key value; do
    [[ -z "${key}" || "${key}" == \#* ]] && continue
    key="${key#"${key%%[![:space:]]*}"}"
    key="${key%"${key##*[![:space:]]}"}"
    if [[ "${key}" =~ ^[A-Za-z_][A-Za-z0-9_]*$ && -z "${!key+x}" ]]; then
      value="${value#"${value%%[![:space:]]*}"}"
      value="${value%"${value##*[![:space:]]}"}"
      value="${value%\"}"
      value="${value#\"}"
      export "${key}=${value}"
    fi
  done < ".env"
fi

HOST="${BIRDMARK_API_HOST:-127.0.0.1}"
PORT="${BIRDMARK_API_PORT:-8100}"
PY=".venv/bin/python"
URL="http://${HOST}:${PORT}"

export PYTHONPATH="${PWD}${PYTHONPATH:+:${PYTHONPATH}}"

echo "[Birdmark API] Working directory: ${PWD}"

if [[ ! -x "${PY}" ]]; then
  echo "[Birdmark API] Creating virtual environment..."
  python3 -m venv .venv
fi

echo "[Birdmark API] Checking dependencies..."
if ! "${PY}" -c "import fastapi, uvicorn, multipart, httpx, PIL" >/dev/null 2>&1; then
  echo "[Birdmark API] Installing API dependencies..."
  "${PY}" -m pip install -r apps/api/requirements.txt
fi

if [[ "${BIRDMARK_CHECK_ONLY:-0}" == "1" ]]; then
  echo "[Birdmark API] Preflight checks passed."
  exit 0
fi

echo "[Birdmark API] Starting business API at ${URL} ..."
exec "${PY}" -m uvicorn apps.api.app.main:app --host "${HOST}" --port "${PORT}"
