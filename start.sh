#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
PYTHON="${PYTHON:-python3}"
if [ ! -d .venv ]; then
  "$PYTHON" -m venv .venv
fi
. .venv/bin/activate
python -m pip install -r requirements.txt
exec uvicorn app.main:app --host 127.0.0.1 --port "${BURN_LEDGER_PORT:-8795}"
