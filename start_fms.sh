#!/usr/bin/env bash

set -Eeuo pipefail

# FMS development launcher
# - Docker: Zenoh Router only
# - Host: FastAPI, Vite, ROS 2 daemon, zenoh-bridge-ros2dds

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FRONTEND_DIR="$PROJECT_DIR/frontend"
COMPOSE_FILE="${FMS_COMPOSE_FILE:-$PROJECT_DIR/infra/docker-compose.yml}"
LOG_DIR="${FMS_LOG_DIR:-$PROJECT_DIR/logs}"

BACKEND_PORT="${FMS_BACKEND_PORT:-8000}"
FRONTEND_PORT="${FMS_FRONTEND_PORT:-5173}"
ZENOH_PORT="${FMS_ZENOH_PORT:-7447}"

VENV_DIR="${FMS_VENV_DIR:-$HOME/venv/robot}"
PYTHON_BIN="${FMS_PYTHON:-$VENV_DIR/bin/python}"
NVM_DIR="${NVM_DIR:-$HOME/.nvm}"

ROS_DISTRO="${ROS_DISTRO:-jazzy}"
ROS_SETUP="${FMS_ROS_SETUP:-/opt/ros/$ROS_DISTRO/setup.bash}"
ROS_WS_SETUP="${FMS_ROS_WS_SETUP:-$PROJECT_DIR/robots_ws/install/setup.bash}"
ROS_DOMAIN_ID="${ROS_DOMAIN_ID:-15}"
RMW_IMPLEMENTATION="${RMW_IMPLEMENTATION:-rmw_cyclonedds_cpp}"
ROS_AUTOMATIC_DISCOVERY_RANGE="${ROS_AUTOMATIC_DISCOVERY_RANGE:-LOCALHOST}"

ZENOH_CONNECT_ENDPOINT="${FMS_ZENOH_CONNECT_ENDPOINT:-tcp/127.0.0.1:$ZENOH_PORT}"
BRIDGE_BIN="${FMS_ZENOH_BRIDGE_BIN:-zenoh-bridge-ros2dds}"

CLEANUP_ON_EXIT=0
mkdir -p "$LOG_DIR"

log() {
    printf '[FMS] %s\n' "$*"
}

fail() {
    printf '[FMS][ERROR] %s\n' "$*" >&2
    exit 1
}

cleanup_failed_start() {
    local status=$?

    if [ "$status" -ne 0 ] && [ "$CLEANUP_ON_EXIT" -eq 1 ]; then
        trap - EXIT
        printf '[FMS][ERROR] Startup failed; stopping the partially started stack.\n' >&2
        set +e
        "$PROJECT_DIR/stop_fms.sh"
    fi

    exit "$status"
}

trap cleanup_failed_start EXIT

select_docker_command() {
    command -v docker >/dev/null 2>&1 || fail "docker command not found"

    if docker info >/dev/null 2>&1; then
        DOCKER=(docker)
    else
        command -v sudo >/dev/null 2>&1 || fail "Docker is unavailable to the current user"
        DOCKER=(sudo docker)
        "${DOCKER[@]}" info >/dev/null 2>&1 || fail "Docker daemon is unavailable"
    fi

    "${DOCKER[@]}" compose version >/dev/null 2>&1 || fail "docker compose plugin not found"
}

load_node_environment() {
    export NVM_DIR
    if [ -s "$NVM_DIR/nvm.sh" ]; then
        # nvm scripts are not nounset-safe.
        set +u
        # shellcheck disable=SC1090
        source "$NVM_DIR/nvm.sh"
        set -u
    fi

    command -v node >/dev/null 2>&1 || fail "node command not found"
    command -v npm >/dev/null 2>&1 || fail "npm command not found"
}

load_ros_environment() {
    [ -f "$ROS_SETUP" ] || fail "ROS setup not found: $ROS_SETUP"

    # ROS-generated setup files may read variables before defining them.
    set +u
    # shellcheck disable=SC1090
    source "$ROS_SETUP"
    if [ -f "$ROS_WS_SETUP" ]; then
        # shellcheck disable=SC1090
        source "$ROS_WS_SETUP"
    fi
    set -u

    export ROS_DOMAIN_ID
    export RMW_IMPLEMENTATION
    export ROS_AUTOMATIC_DISCOVERY_RANGE
    unset ROS_LOCALHOST_ONLY || true
}

wait_for_tcp() {
    local host="$1"
    local port="$2"
    local timeout="${3:-30}"
    local count

    for ((count = 0; count < timeout; count++)); do
        if "$PYTHON_BIN" -c \
            'import socket, sys; socket.create_connection((sys.argv[1], int(sys.argv[2])), timeout=1).close()' \
            "$host" "$port" >/dev/null 2>&1; then
            return 0
        fi
        sleep 1
    done
    return 1
}

wait_for_http() {
    local url="$1"
    local timeout="${2:-60}"
    local count

    command -v curl >/dev/null 2>&1 || return 0
    for ((count = 0; count < timeout; count++)); do
        if curl -fsS --max-time 2 "$url" >/dev/null 2>&1; then
            return 0
        fi
        sleep 1
    done
    return 1
}

wait_for_stable_process() {
    local pid="$1"
    local seconds="${2:-2}"

    sleep "$seconds"
    kill -0 "$pid" >/dev/null 2>&1
}

[ -f "$COMPOSE_FILE" ] || fail "Compose file not found: $COMPOSE_FILE"
[ -x "$PYTHON_BIN" ] || fail "Python executable not found: $PYTHON_BIN"
[ -d "$FRONTEND_DIR" ] || fail "Frontend directory not found: $FRONTEND_DIR"

select_docker_command
load_node_environment
load_ros_environment
command -v "$BRIDGE_BIN" >/dev/null 2>&1 || fail "Bridge binary not found: $BRIDGE_BIN"

# Clean up PID-less legacy processes and the router before starting a new stack.
if [ "${FMS_CLEAN_START:-1}" = "1" ]; then
    "$PROJECT_DIR/stop_fms.sh"
fi
CLEANUP_ON_EXIT=1

log "Starting Zenoh Router with Docker Compose"
"${DOCKER[@]}" compose -f "$COMPOSE_FILE" up -d zenoh-router
wait_for_tcp "127.0.0.1" "$ZENOH_PORT" 30 || {
    "${DOCKER[@]}" compose -f "$COMPOSE_FILE" logs --tail 100 zenoh-router || true
    fail "Zenoh Router did not open port $ZENOH_PORT"
}

if command -v ros2 >/dev/null 2>&1; then
    ros2 daemon start >/dev/null 2>&1 || true
fi

log "Starting zenoh-bridge-ros2dds on the host"
nohup "$BRIDGE_BIN" \
    -d "$ROS_DOMAIN_ID" \
    --ros-automatic-discovery-range "$ROS_AUTOMATIC_DISCOVERY_RANGE" \
    -e "$ZENOH_CONNECT_ENDPOINT" \
    client \
    >"$LOG_DIR/zenoh_bridge.log" 2>&1 &
BRIDGE_PID=$!
printf '%s\n' "$BRIDGE_PID" >"$LOG_DIR/zenoh_bridge.pid"
wait_for_stable_process "$BRIDGE_PID" 2 || {
    tail -n 100 "$LOG_DIR/zenoh_bridge.log" || true
    fail "zenoh-bridge-ros2dds exited during startup"
}

log "Starting FastAPI backend on the host"
cd "$PROJECT_DIR"
nohup "$PYTHON_BIN" -m uvicorn backend.app.main:app \
    --host 0.0.0.0 \
    --port "$BACKEND_PORT" \
    >"$LOG_DIR/backend.log" 2>&1 &
BACKEND_PID=$!
printf '%s\n' "$BACKEND_PID" >"$LOG_DIR/backend.pid"
wait_for_http "http://127.0.0.1:$BACKEND_PORT/health" 60 || {
    tail -n 100 "$LOG_DIR/backend.log" || true
    fail "Backend health check failed"
}

log "Starting Vite frontend on the host"
cd "$FRONTEND_DIR"
nohup npm run dev -- \
    --host 0.0.0.0 \
    --port "$FRONTEND_PORT" \
    >"$LOG_DIR/frontend.log" 2>&1 &
FRONTEND_PID=$!
printf '%s\n' "$FRONTEND_PID" >"$LOG_DIR/frontend.pid"
wait_for_http "http://127.0.0.1:$FRONTEND_PORT/" 60 || {
    tail -n 100 "$LOG_DIR/frontend.log" || true
    fail "Frontend health check failed"
}

CLEANUP_ON_EXIT=0

cat <<EOF

========================================
 FMS start complete
========================================
Frontend     : http://127.0.0.1:$FRONTEND_PORT
Backend      : http://127.0.0.1:$BACKEND_PORT
Zenoh Router : $ZENOH_CONNECT_ENDPOINT

Logs:
  Backend      : $LOG_DIR/backend.log
  Frontend     : $LOG_DIR/frontend.log
  Zenoh Bridge : $LOG_DIR/zenoh_bridge.log
  Zenoh Router : ${DOCKER[*]} compose -f $COMPOSE_FILE logs -f zenoh-router
========================================
EOF
