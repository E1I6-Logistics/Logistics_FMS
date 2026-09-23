#!/usr/bin/env bash

set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOG_DIR="$PROJECT_DIR/logs"

stop_from_pid_file() {
    local name="$1"
    local pid_file="$2"

    if [ ! -f "$pid_file" ]; then
        echo "$name: pid file not found"
        return
    fi

    local pid
    pid="$(cat "$pid_file")"
    if kill -0 "$pid" >/dev/null 2>&1; then
        kill "$pid"
        echo "$name stopped (pid=$pid)"
    else
        echo "$name already stopped"
    fi
    rm -f "$pid_file"
}

stop_from_pid_file "Backend" "$LOG_DIR/backend.pid"
stop_from_pid_file "Frontend" "$LOG_DIR/frontend.pid"
