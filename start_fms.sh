#!/usr/bin/env bash

set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FRONTEND_DIR="$PROJECT_DIR/frontend"
LOG_DIR="$PROJECT_DIR/logs"
BACKEND_PORT="${FMS_BACKEND_PORT:-8000}"
FRONTEND_PORT="${FMS_FRONTEND_PORT:-5173}"
DEFAULT_PYTHON="$HOME/venv/robot/bin/python"
if [ ! -x "$DEFAULT_PYTHON" ]; then
    DEFAULT_PYTHON="python3"
fi
PYTHON_BIN="${FMS_PYTHON:-$DEFAULT_PYTHON}"

mkdir -p "$LOG_DIR"

if ! command -v "$PYTHON_BIN" >/dev/null 2>&1; then
    echo "[ERROR] Python executable not found: $PYTHON_BIN"
    exit 1
fi

if ! command -v npm >/dev/null 2>&1; then
    echo "[ERROR] npm not found"
    exit 1
fi

cd "$PROJECT_DIR"
nohup "$PYTHON_BIN" -m uvicorn backend.app.main:app \
    --host 0.0.0.0 \
    --port "$BACKEND_PORT" \
    > "$LOG_DIR/backend.log" 2>&1 &
echo $! > "$LOG_DIR/backend.pid"

cd "$FRONTEND_DIR"
nohup npm run dev -- --host 0.0.0.0 --port "$FRONTEND_PORT" \
    > "$LOG_DIR/frontend.log" 2>&1 &
echo $! > "$LOG_DIR/frontend.pid"

echo "FMS mock backend and frontend started"
echo "Backend : http://127.0.0.1:$BACKEND_PORT"
echo "Frontend: http://127.0.0.1:$FRONTEND_PORT"
echo "Logs    : $LOG_DIR"
