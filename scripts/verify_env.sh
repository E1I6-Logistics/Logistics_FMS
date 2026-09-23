#!/usr/bin/env bash

set +e


# ============================================================
# Path
# ============================================================

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"


VENV_DIR="$HOME/venv/robot"

FAIL=0


# ============================================================
# Helpers
# ============================================================

ok() {
    echo "[OK] $1"
}


fail() {
    echo "[FAIL] $1"
    FAIL=1
}


echo "========================================"
echo " Logistics_FMS Environment Verification"
echo "========================================"
echo "Project : $PROJECT_DIR"
echo "Arch    : $(uname -m)"
echo "========================================"


# ============================================================
# OS
# ============================================================

echo ""
echo "===== OS ====="

grep -E '^(NAME|VERSION|VERSION_ID)=' \
    /etc/os-release

if grep -q 'VERSION_ID="24.04"' /etc/os-release; then
    ok "Ubuntu 24.04"
else
    fail "Ubuntu 24.04 required"
fi


# ============================================================
# Jetson
# ============================================================

echo ""
echo "===== PLATFORM ====="

if [ -f /etc/nv_tegra_release ] ||
   dpkg-query -W nvidia-l4t-core >/dev/null 2>&1; then

    echo "Platform: NVIDIA Jetson"

else

    echo "Platform: Standard PC / Linux"

fi


# ============================================================
# ROS 2
# ============================================================

echo ""
echo "===== ROS 2 ====="

if [ -f /opt/ros/jazzy/setup.bash ]; then

    source /opt/ros/jazzy/setup.bash

    ok "ROS 2 Jazzy"

else

    fail "ROS 2 Jazzy"

fi


echo "ROS_DISTRO=${ROS_DISTRO:-NOT SET}"


for PKG in \
    nav2_bringup \
    nav2_route \
    robot_localization \
    rmw_cyclonedds_cpp \
    rmw_fastrtps_cpp \
    turtlebot3_msgs

do

    if ros2 pkg prefix "$PKG" >/dev/null 2>&1; then

        ok "$PKG"

    else

        fail "$PKG"

    fi

done


# ============================================================
# Python
# ============================================================

echo ""
echo "===== PYTHON ====="

if [ -f "$VENV_DIR/bin/activate" ]; then

    source "$VENV_DIR/bin/activate"

    ok "Python venv"

else

    fail "Python venv: $VENV_DIR"

fi


python --version 2>/dev/null || fail "Python"


python - <<'PY'

import sys

modules = [
    "fastapi",
    "uvicorn",
    "zenoh",
    "yaml",
    "PIL",
    "pydantic",
    "rclpy",
]

failed = []

for module in modules:

    try:
        __import__(module)

    except Exception as exc:
        failed.append((module, str(exc)))


try:
    from geometry_msgs.msg import Pose
    from std_msgs.msg import String
    from turtlebot3_msgs.msg import SensorState

except Exception as exc:
    failed.append(("ROS message imports", str(exc)))


if failed:

    for module, error in failed:
        print(f"[FAIL] {module}: {error}")

    sys.exit(1)

print("[OK] Python / ROS imports")

PY


if [ $? -ne 0 ]; then
    FAIL=1
fi


# ============================================================
# Zenoh
# ============================================================

echo ""
echo "===== ZENOH ====="

# ------------------------------------------------------------
# Zenoh Router
#
# Main PC may use:
#   1. native/snap zenohd
#   2. Docker fms-zenoh-router
# ------------------------------------------------------------

if command -v zenohd >/dev/null 2>&1; then

    echo "zenohd path: $(command -v zenohd)"
    zenohd --version
    ok "Zenoh Router (native/snap zenohd)"

elif command -v docker >/dev/null 2>&1 &&
     sudo docker ps -a \
        --format '{{.Names}}' \
        | grep -qx "fms-zenoh-router"; then

    ok "Zenoh Router (Docker: fms-zenoh-router)"

else

    fail "Zenoh Router"

fi


# ------------------------------------------------------------
# ROS2DDS Bridge
# ------------------------------------------------------------

if command -v zenoh-bridge-ros2dds >/dev/null 2>&1; then

    zenoh-bridge-ros2dds --version
    ok "zenoh-bridge-ros2dds"

else

    fail "zenoh-bridge-ros2dds"

fi


# ============================================================
# Node.js
# ============================================================

echo ""
echo "===== NODE ====="

export NVM_DIR="$HOME/.nvm"

# NVM이 있으면 로드
if [ -s "$NVM_DIR/nvm.sh" ]; then
    source "$NVM_DIR/nvm.sh"
fi

if command -v node >/dev/null 2>&1; then
    echo "Node: $(node --version)"
    ok "node"
else
    fail "node"
fi

if command -v npm >/dev/null 2>&1; then
    echo "npm : $(npm --version)"
    ok "npm"
else
    fail "npm"
fi


# ============================================================
# Docker
# ============================================================

echo ""
echo "===== DOCKER ====="

if command -v docker >/dev/null 2>&1; then

    docker --version

    docker compose version

else

    fail "Docker"

fi


# ============================================================
# Frontend
# ============================================================

echo ""
echo "===== FRONTEND ====="

if [ -d "$PROJECT_DIR/frontend/node_modules" ]; then

    ok "node_modules"

else

    fail "node_modules"

fi


# ============================================================
# Network
# ============================================================

echo ""
echo "===== NETWORK ====="

ip -br -4 addr


# ============================================================
# Result
# ============================================================

echo ""
echo "========================================"

if [ "$FAIL" -eq 0 ]; then

    echo " Environment Verification: PASS"

else

    echo " Environment Verification: FAIL"

fi

echo "========================================"

exit "$FAIL"
