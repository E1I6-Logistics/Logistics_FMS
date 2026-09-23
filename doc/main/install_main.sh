#!/usr/bin/env bash

set -euo pipefail


# ============================================================
# Path / Environment
# ============================================================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

ROS_DISTRO="jazzy"
ZENOH_VERSION="1.9.0"

ARCH="$(uname -m)"


# ============================================================
# System Check
# ============================================================

if ! grep -q 'VERSION_ID="24.04"' /etc/os-release; then
    echo "[ERROR] Ubuntu 24.04 is required."
    exit 1
fi

case "$ARCH" in
    x86_64)
        PLATFORM="PC"
        ;;

    aarch64)
        PLATFORM="JETSON"
        ;;

    *)
        echo "[ERROR] Unsupported architecture: $ARCH"
        exit 1
        ;;
esac


if [ ! -f "/opt/ros/$ROS_DISTRO/setup.bash" ]; then
    echo "[ERROR] ROS 2 $ROS_DISTRO not found."
    exit 1
fi


echo "========================================"
echo " FMS Main Installation"
echo "========================================"
echo "Platform : $PLATFORM"
echo "Arch     : $ARCH"
echo "ROS      : $ROS_DISTRO"
echo "Zenoh    : $ZENOH_VERSION"
echo "========================================"


# ============================================================
# Zenoh Repository
# ============================================================

add_zenoh_repo() {

    sudo install -d -m 0755 /etc/apt/keyrings

    curl -fsSL \
        https://download.eclipse.org/zenoh/debian-repo/zenoh-public-key \
        | sudo gpg --dearmor --yes \
            --output /etc/apt/keyrings/zenoh-public-key.gpg

    echo \
        "deb [signed-by=/etc/apt/keyrings/zenoh-public-key.gpg] https://download.eclipse.org/zenoh/debian-repo/ /" \
        | sudo tee /etc/apt/sources.list.d/zenoh.list \
            >/dev/null

    sudo apt update
}


# ============================================================
# 1. Main Dependencies
# ============================================================

echo "[1/6] Install Main dependencies"

sudo apt update

mapfile -t PKGS < <(
    grep -Ev '^[[:space:]]*(#|$)' \
        "$SCRIPT_DIR/requirements.txt"
)

sudo apt install -y "${PKGS[@]}"


# ============================================================
# 2. Zenoh Repository
# ============================================================

echo "[2/6] Configure Eclipse Zenoh repository"

add_zenoh_repo


# ============================================================
# 3. Zenoh
# ============================================================

echo "[3/6] Install Zenoh $ZENOH_VERSION"

sudo apt install -y \
    "zenoh=$ZENOH_VERSION" \
    "zenoh-bridge-ros2dds=$ZENOH_VERSION" \
    --allow-downgrades


# ============================================================
# 4. Hold Zenoh
# ============================================================

echo "[4/6] Hold Zenoh packages"

sudo apt-mark hold \
    zenoh \
    zenoh-bridge-ros2dds


# ============================================================
# 5. ROS RMW Verification
# ============================================================

echo "[5/6] Verify ROS RMW"

source "/opt/ros/$ROS_DISTRO/setup.bash"

ros2 pkg prefix rmw_cyclonedds_cpp
ros2 pkg prefix rmw_fastrtps_cpp
ros2 pkg prefix turtlebot3_msgs


# ============================================================
# 6. Zenoh Verification
# ============================================================

echo "[6/6] Verify Zenoh"

zenohd --version
zenoh-bridge-ros2dds --version


echo ""
echo "========================================"
echo " Main Installation Complete"
echo "========================================"
echo "Platform : $PLATFORM"
echo "ROS      : $ROS_DISTRO"
echo "Zenoh    : $ZENOH_VERSION"
echo "========================================"
