#!/usr/bin/env bash
# Agenora 本地开发：同时启动 FastAPI (:8000) 和 Next.js (:3000)。
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
BACKEND_PYTHON="$ROOT_DIR/backend/.venv/bin/python"

if [[ ! -x "$BACKEND_PYTHON" ]]; then
  echo "✗ Backend virtual environment is missing. See README local setup first." >&2
  exit 1
fi
if [[ ! -d "$ROOT_DIR/frontend/node_modules" ]]; then
  echo "✗ Frontend dependencies are missing. Run: cd frontend && npm ci" >&2
  exit 1
fi
if [[ ! -f "$ROOT_DIR/backend/.env" || ! -f "$ROOT_DIR/frontend/.env" ]]; then
  echo "✗ Missing backend/.env or frontend/.env. Copy their .env.example files first." >&2
  exit 1
fi

cleanup() {
  trap - EXIT INT TERM
  kill "$BACKEND_PID" "$FRONTEND_PID" 2>/dev/null || true
  wait "$BACKEND_PID" "$FRONTEND_PID" 2>/dev/null || true
}

(
  cd "$ROOT_DIR/backend"
  # No --reload: file watches restart the process mid-SSE and drop chat streams.
  # Restart manually via ./scripts/dev.sh after backend code changes.
  exec "$BACKEND_PYTHON" -m uvicorn src.app:app \
    --host 0.0.0.0 \
    --port 8000
) &
BACKEND_PID=$!

(
  cd "$ROOT_DIR/frontend"
  exec npm run dev
) &
FRONTEND_PID=$!

trap cleanup EXIT INT TERM
wait "$BACKEND_PID" "$FRONTEND_PID"
