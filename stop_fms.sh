#!/usr/bin/env bash

set -u

# Stops the FMS development stack.
# - Docker: Zenoh Router
# - Host: FastAPI, Vite, ROS 2 daemon, zenoh-bridge-ros2dds
# It also stops containers/processes left by earlier launcher versions.

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
COMPOSE_FILE="${FMS_COMPOSE_FILE:-$PROJECT_DIR/infra/docker-compose.yml}"
LOG_DIR="${FMS_LOG_DIR:-$PROJECT_DIR/logs}"

BACKEND_PORT="${FMS_BACKEND_PORT:-8000}"
FRONTEND_PORT="${FMS_FRONTEND_PORT:-5173}"
ZENOH_PORT="${FMS_ZENOH_PORT:-7447}"
ROS_DISTRO="${ROS_DISTRO:-jazzy}"
ROS_SETUP="${FMS_ROS_SETUP:-/opt/ros/$ROS_DISTRO/setup.bash}"

log() {
    printf '[FMS] %s\n' "$*"
}

select_docker_command() {
    if ! command -v docker >/dev/null 2>&1; then
        return 1
    fi

    if docker info >/dev/null 2>&1; then
        DOCKER=(docker)
    elif command -v sudo >/dev/null 2>&1; then
        DOCKER=(sudo docker)
        "${DOCKER[@]}" info >/dev/null 2>&1 || return 1
    else
        return 1
    fi

    "${DOCKER[@]}" compose version >/dev/null 2>&1
}

stop_pid_file() {
    local label="$1"
    local pid_file="$2"

    [ -f "$pid_file" ] || return

    local pid
    pid="$(tr -cd '0-9' <"$pid_file")"
    if [ -n "$pid" ] && kill -0 "$pid" >/dev/null 2>&1; then
        # Stop children first (for example npm -> Vite), then the saved parent.
        pkill -TERM -P "$pid" >/dev/null 2>&1 || true
        kill -TERM "$pid" >/dev/null 2>&1 || true
        log "$label: stop requested for pid $pid"
    fi
    rm -f "$pid_file"
}

stop_matching_processes() {
    local label="$1"
    local pattern="$2"

    if pgrep -f "$pattern" >/dev/null 2>&1; then
        pkill -TERM -f "$pattern" >/dev/null 2>&1 || true
        sleep 1
        if pgrep -f "$pattern" >/dev/null 2>&1; then
            pkill -KILL -f "$pattern" >/dev/null 2>&1 || true
        fi
        log "$label: stopped"
    fi
}

stop_port_owner() {
    local label="$1"
    local port="$2"

    command -v fuser >/dev/null 2>&1 || return
    if fuser "${port}/tcp" >/dev/null 2>&1; then
        fuser -k "${port}/tcp" >/dev/null 2>&1 || true
        log "$label: stopped listener on port $port"
    fi
}

stop_legacy_container() {
    local name="$1"

    if "${DOCKER[@]}" container inspect "$name" >/dev/null 2>&1 && \
       [ "$("${DOCKER[@]}" inspect -f '{{.State.Running}}' "$name" 2>/dev/null)" = "true" ]; then
        "${DOCKER[@]}" stop --time 10 "$name" >/dev/null || true
        log "$name: legacy container stopped"
    fi
}

echo "========================================"
echo " FMS stop"
echo "========================================"

# Host applications in reverse startup order.
stop_pid_file "Frontend" "$LOG_DIR/frontend.pid"
stop_pid_file "Backend" "$LOG_DIR/backend.pid"
stop_pid_file "Zenoh bridge" "$LOG_DIR/zenoh_bridge.pid"

# Fallback for PID-less processes created by older launchers.
stop_matching_processes "Vite frontend" '[v]ite.*--host'
stop_matching_processes "npm frontend" '[n]pm[[:space:]]+run[[:space:]]+dev'
stop_matching_processes "FastAPI backend" '[u]vicorn[[:space:]]+backend\.app\.main:app'
stop_matching_processes "Zenoh ROS2DDS bridge" '[z]enoh-bridge-ros2dds'

stop_port_owner "Frontend" "$FRONTEND_PORT"
stop_port_owner "Backend" "$BACKEND_PORT"

# Make ros2 available even when stop_fms.sh is run from a plain shell.
if [ -f "$ROS_SETUP" ]; then
    set +u
    # shellcheck disable=SC1090
    source "$ROS_SETUP" >/dev/null 2>&1 || true
    set -u
fi

if command -v ros2 >/dev/null 2>&1; then
    ros2 daemon stop >/dev/null 2>&1 || true
    log "ROS 2 daemon: stop requested"
fi

# Stop the Compose-managed Zenoh Router.
if select_docker_command; then
    if [ -f "$COMPOSE_FILE" ]; then
        "${DOCKER[@]}" compose -f "$COMPOSE_FILE" stop zenoh-router >/dev/null 2>&1 || true
        log "Zenoh Router: stop requested"
    fi

    # Migration cleanup: stop containers created by the discarded
    # frontend/backend/zenohd Docker launcher, without deleting them.
    stop_legacy_container "fms-frontend"
    stop_legacy_container "fms-backend"
    stop_legacy_container "fms-zenohd"
else
    log "Docker unavailable; Zenoh Router stop skipped"
fi

# Check for a separately started host zenohd only after the Docker router has
# stopped, otherwise the container process can be mistaken for a host process.
stop_matching_processes "Host zenohd" '[z]enohd'

# Run after Docker stop so a host-networked container is not restarted by its
# Docker restart policy when fuser terminates the listener.
stop_port_owner "Zenoh" "$ZENOH_PORT"

echo "========================================"
echo " FMS stop complete"
echo "========================================"
