#!/usr/bin/env bash

set -o pipefail


# ============================================================
# FMS Main PC Start Script
#
# Common:
#   - x86_64 Main PC
#   - NVIDIA Jetson aarch64
# ============================================================


PROJECT_DIR="$HOME/Logistics_FMS"

ROS_WS="$PROJECT_DIR/robots_ws"

VENV_DIR="$HOME/venv/robot"

LOG_DIR="$PROJECT_DIR/logs"


ZENOH_PORT=7447

BACKEND_PORT=8000

FRONTEND_PORT=5173


ZENOH_ROUTER="tcp/127.0.0.1:$ZENOH_PORT"


mkdir -p "$LOG_DIR"


# ============================================================
# Helper Functions
# ============================================================

port_in_use() {

    local PORT="$1"

    ss -ltn \
        | awk '{print $4}' \
        | grep -q ":$PORT$"

}


process_running() {

    local NAME="$1"

    pgrep -f "$NAME" \
        >/dev/null 2>&1

}


wait_for_port() {

    local PORT="$1"

    local TIMEOUT="${2:-15}"

    local i


    for ((i=1; i<=TIMEOUT; i++)); do

        if port_in_use "$PORT"; then
            return 0
        fi

        sleep 1

    done


    return 1
}


wait_for_process() {

    local NAME="$1"

    local TIMEOUT="${2:-10}"

    local i


    for ((i=1; i<=TIMEOUT; i++)); do

        if process_running "$NAME"; then
            return 0
        fi

        sleep 1

    done


    return 1
}


# ============================================================
# Platform
# ============================================================

ARCH="$(uname -m)"


case "$ARCH" in

    x86_64)
        PLATFORM="PC"
        ;;

    aarch64)

        if [ -f /etc/nv_tegra_release ] ||
           dpkg-query -W nvidia-l4t-core >/dev/null 2>&1; then

            PLATFORM="JETSON"

        else

            PLATFORM="ARM64"

        fi
        ;;

    *)
        PLATFORM="UNKNOWN"
        ;;

esac


# ============================================================
# Python Virtual Environment
# ============================================================

if [ ! -f "$VENV_DIR/bin/activate" ]; then

    echo "[ERROR] Python venv not found:"
    echo "        $VENV_DIR"

    exit 1

fi


source "$VENV_DIR/bin/activate"


# ============================================================
# Node.js / NVM
# ============================================================

export NVM_DIR="$HOME/.nvm"


export NVM_DIR="$HOME/.nvm"

if [ -s "$NVM_DIR/nvm.sh" ]; then
    source "$NVM_DIR/nvm.sh"
fi


if ! command -v node >/dev/null 2>&1; then

    echo "[ERROR] node not found"

    exit 1

fi


if ! command -v npm >/dev/null 2>&1; then

    echo "[ERROR] npm not found"

    exit 1

fi


# ============================================================
# ROS 2 Environment
# ============================================================

if [ ! -f /opt/ros/jazzy/setup.bash ]; then

    echo "[ERROR] ROS 2 Jazzy not found."

    exit 1

fi


source /opt/ros/jazzy/setup.bash


if [ -f "$ROS_WS/install/setup.bash" ]; then

    source "$ROS_WS/install/setup.bash"

fi


# Main FMS Zenoh Mode

export ROS_DOMAIN_ID=15

export RMW_IMPLEMENTATION=rmw_cyclonedds_cpp

export ROS_AUTOMATIC_DISCOVERY_RANGE=LOCALHOST

unset ROS_LOCALHOST_ONLY


# ============================================================
# Main Network Interface
# ============================================================

detect_main_interface() {

    # --------------------------------------------------------
    # Explicit override
    # --------------------------------------------------------

    if [ -n "${FMS_MAIN_INTERFACE:-}" ]; then

        if ip link show "$FMS_MAIN_INTERFACE" \
            >/dev/null 2>&1; then

            echo "$FMS_MAIN_INTERFACE"

            return 0

        fi


        echo "[ERROR] FMS_MAIN_INTERFACE not found: $FMS_MAIN_INTERFACE" \
            >&2

        return 1

    fi


    # --------------------------------------------------------
    # Prefer Ethernet interface with default route
    #
    # Typical:
    #   PC     : eno1 / enp*
    #   Jetson : enP8p1s0
    # --------------------------------------------------------

    local IFACE


    while read -r IFACE; do

        case "$IFACE" in

            en*|eth*)

                if ip -4 -o addr show dev "$IFACE" scope global \
                    | grep -q .; then

                    echo "$IFACE"

                    return 0

                fi
                ;;

        esac

    done < <(
        ip -4 route show default \
            | awk '{print $5}' \
            | awk '!seen[$0]++'
    )


    # --------------------------------------------------------
    # Fallback: any Ethernet interface with global IPv4
    # --------------------------------------------------------

    while read -r IFACE; do

        case "$IFACE" in

            en*|eth*)

                echo "$IFACE"

                return 0
                ;;

        esac

    done < <(
        ip -4 -o addr show scope global \
            | awk '{print $2}' \
            | awk '!seen[$0]++'
    )


    # --------------------------------------------------------
    # Last fallback: default route
    # --------------------------------------------------------

    ip -4 route show default \
        | awk 'NR == 1 {print $5}'

}


MAIN_INTERFACE="$(detect_main_interface)"


if [ -z "$MAIN_INTERFACE" ]; then

    echo "[ERROR] Main network interface not found."

    exit 1

fi


MAIN_IP="$(
    ip -4 -o addr show dev "$MAIN_INTERFACE" scope global \
        | awk 'NR == 1 {
            split($4, a, "/")
            print a[1]
        }'
)"


if [ -z "$MAIN_IP" ]; then

    echo "[ERROR] IPv4 address not found:"
    echo "        interface=$MAIN_INTERFACE"

    exit 1

fi


# ============================================================
# Header
# ============================================================

echo "========================================"
echo " FMS Server Start"
echo "========================================"

echo "Platform       : $PLATFORM"
echo "Architecture   : $ARCH"
echo "Main Interface : $MAIN_INTERFACE"
echo "Main PC IP     : $MAIN_IP"
echo "ROS Domain ID  : $ROS_DOMAIN_ID"
echo "ROS RMW        : $RMW_IMPLEMENTATION"
echo "ROS Discovery  : $ROS_AUTOMATIC_DISCOVERY_RANGE"
echo "Node           : $(node -v)"
echo "npm            : $(npm -v)"

echo ""


# ============================================================
# Zenoh Router
# ============================================================

if sudo docker ps \
    --format '{{.Names}}' \
    | grep -qx "fms-zenoh-router"; then

    echo "[Zenoh Router] ONLINE"


elif sudo docker ps -a \
    --format '{{.Names}}' \
    | grep -qx "fms-zenoh-router"; then

    sudo docker start fms-zenoh-router \
        >/dev/null


    if wait_for_port "$ZENOH_PORT" 10; then

        echo "[Zenoh Router] STARTED"

    else

        echo "[Zenoh Router] FAILED"

        echo "  Check:"
        echo "  sudo docker logs fms-zenoh-router"

    fi


else

    echo "[Zenoh Router] container not found"

    echo "Starting Docker Compose..."


    cd "$PROJECT_DIR/infra"


    sudo docker compose up -d zenoh-router


    if wait_for_port "$ZENOH_PORT" 15; then

        echo "[Zenoh Router] STARTED"

    else

        echo "[Zenoh Router] FAILED"

        echo "  Check:"
        echo "  sudo docker logs fms-zenoh-router"

    fi

fi


# ============================================================
# Zenoh ROS2DDS Bridge
# ============================================================

if process_running "zenoh-bridge-ros2dds"; then

    echo "[Zenoh Bridge] ONLINE"

else

    nohup zenoh-bridge-ros2dds \
        -d "$ROS_DOMAIN_ID" \
        --ros-automatic-discovery-range LOCALHOST \
        -e "$ZENOH_ROUTER" \
        client \
        > "$LOG_DIR/zenoh_bridge.log" \
        2>&1 &


    if wait_for_process "zenoh-bridge-ros2dds" 10; then

        echo "[Zenoh Bridge] STARTED"

    else

        echo "[Zenoh Bridge] FAILED"

        echo "  Check log:"
        echo "  $LOG_DIR/zenoh_bridge.log"

    fi

fi


# ============================================================
# FastAPI Backend
# ============================================================

if port_in_use "$BACKEND_PORT"; then

    echo "[Backend] ONLINE : http://$MAIN_IP:$BACKEND_PORT"

else

    cd "$PROJECT_DIR"


    nohup python -m uvicorn \
        backend.app.main:app \
        --host 0.0.0.0 \
        --port "$BACKEND_PORT" \
        > "$LOG_DIR/backend.log" \
        2>&1 &


    if wait_for_port "$BACKEND_PORT" 15; then

        echo "[Backend] STARTED : http://$MAIN_IP:$BACKEND_PORT"

    else

        echo "[Backend] FAILED"

        echo "  Check log:"
        echo "  $LOG_DIR/backend.log"

    fi

fi


# ============================================================
# Vite Frontend
# ============================================================

if port_in_use "$FRONTEND_PORT"; then

    echo "[Frontend] ONLINE : http://$MAIN_IP:$FRONTEND_PORT"

else

    cd "$PROJECT_DIR/frontend"


    nohup npm run dev -- --host 0.0.0.0 \
        > "$LOG_DIR/frontend.log" \
        2>&1 &


    if wait_for_port "$FRONTEND_PORT" 15; then

        echo "[Frontend] STARTED : http://$MAIN_IP:$FRONTEND_PORT"

    else

        echo "[Frontend] FAILED"

        echo "  Check log:"
        echo "  $LOG_DIR/frontend.log"

    fi

fi


# ============================================================
# Result
# ============================================================

echo ""
echo "========================================"
echo " FMS Start Complete"
echo "========================================"

echo "Interface: $MAIN_INTERFACE"
echo "Zenoh   : $MAIN_IP:$ZENOH_PORT"
echo "Backend : http://$MAIN_IP:$BACKEND_PORT"
echo "Frontend: http://$MAIN_IP:$FRONTEND_PORT"

echo ""

echo "Logs:"
echo "  Zenoh Router : sudo docker logs fms-zenoh-router"
echo "  Zenoh Bridge : $LOG_DIR/zenoh_bridge.log"
echo "  Backend      : $LOG_DIR/backend.log"
echo "  Frontend     : $LOG_DIR/frontend.log"

echo "========================================"
