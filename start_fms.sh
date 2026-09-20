#!/bin/bash

# ============================================================
# FMS Main PC Start Script
# ============================================================

PROJECT_DIR="$HOME/Logistics_FMS"
ROS_WS="$PROJECT_DIR/robots_ws"
LOG_DIR="$PROJECT_DIR/logs"

ZENOH_PORT=7447
BACKEND_PORT=8000
FRONTEND_PORT=5173

ZENOH_ROUTER="tcp/127.0.0.1:$ZENOH_PORT"

mkdir -p "$LOG_DIR"


# ============================================================
# Check Function
# ============================================================

port_in_use() {
    local PORT="$1"

    ss -ltn | awk '{print $4}' | grep -q ":$PORT$"
}


process_running() {
    local NAME="$1"

    pgrep -f "$NAME" > /dev/null 2>&1
}


# ============================================================
# ROS2 Environment
# ============================================================

source /opt/ros/jazzy/setup.bash

if [ -f "$ROS_WS/install/setup.bash" ]; then
    source "$ROS_WS/install/setup.bash"
fi
export ROS_AUTOMATIC_DISCOVERY_RANGE=LOCALHOST

# ============================================================
# Main PC IP
# ============================================================

MAIN_IP=$(hostname -I | awk '{print $1}')


echo "========================================"
echo " FMS Server Start"
echo "========================================"

echo "Main PC IP    : $MAIN_IP"
echo "ROS Domain ID : ${ROS_DOMAIN_ID:-0}"
echo "ROS Discovery : $ROS_AUTOMATIC_DISCOVERY_RANGE"

# ============================================================
# Zenoh Router
# ============================================================

if sudo docker ps --format '{{.Names}}' | grep -qx "fms-zenoh-router"; then
    echo "[Zenoh Router] ONLINE"

elif sudo docker ps -a --format '{{.Names}}' | grep -qx "fms-zenoh-router"; then
    sudo docker start fms-zenoh-router > /dev/null
    sleep 1

    if sudo docker ps --format '{{.Names}}' | grep -qx "fms-zenoh-router"; then
        echo "[Zenoh Router] STARTED"
    else
        echo "[Zenoh Router] FAILED"
    fi

else
    echo "[Zenoh Router] 컨테이너 없음"
fi


# ============================================================
# Zenoh ROS2DDS Bridge
# ============================================================

if process_running "zenoh-bridge-ros2dds"; then

    echo "[Zenoh Bridge] ONLINE"

else

    nohup zenoh-bridge-ros2dds \
        --ros-automatic-discovery-range LOCALHOST \
        -e "$ZENOH_ROUTER" \
        client \
        > "$LOG_DIR/zenoh_bridge.log" \
        2>&1 &

    sleep 2

    if process_running "zenoh-bridge-ros2dds"; then

        echo "[Zenoh Bridge] STARTED"

    else

        echo "[Zenoh Bridge] FAILED"

    fi

fi


# ============================================================
# FastAPI Backend
# ============================================================

if port_in_use "$BACKEND_PORT"; then

    echo "[Backend] ONLINE : http://$MAIN_IP:$BACKEND_PORT"

else

    cd "$PROJECT_DIR"

    nohup python -m uvicorn backend.app.main:app \
        --host 0.0.0.0 \
        --port "$BACKEND_PORT" \
        > "$LOG_DIR/backend.log" \
        2>&1 &

    sleep 2

    if port_in_use "$BACKEND_PORT"; then

        echo "[Backend] STARTED : http://$MAIN_IP:$BACKEND_PORT"

    else

        echo "[Backend] FAILED"

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

    sleep 2

    if port_in_use "$FRONTEND_PORT"; then

        echo "[Frontend] STARTED : http://$MAIN_IP:$FRONTEND_PORT"

    else

        echo "[Frontend] FAILED"

    fi

fi


# ============================================================
# Result
# ============================================================

echo ""
echo "========================================"
echo " FMS Start Complete"
echo "========================================"

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