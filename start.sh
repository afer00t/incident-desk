#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

if [ -f .env ]; then
  set -a; . ./.env; set +a
fi

if [ -z "${CLOCKED_API_KEY:-}" ]; then
  echo "CLOCKED_API_KEY not set — running offline demo (MOCK mode)" >&2
fi

exec python3 -m uvicorn app:app --host 127.0.0.1 --port "${PORT:-8777}"