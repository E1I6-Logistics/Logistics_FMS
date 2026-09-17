#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

[[ -f /opt/ros/jazzy/setup.bash ]] || {
    echo "ERROR: ROS 2 Jazzy not found."
    exit 1
}


add_zenoh_repo() {
    sudo install -d -m 0755 /etc/apt/keyrings

    curl -L https://download.eclipse.org/zenoh/debian-repo/zenoh-public-key \
      | sudo gpg --dearmor --yes \
        --output /etc/apt/keyrings/zenoh-public-key.gpg

    echo "deb [signed-by=/etc/apt/keyrings/zenoh-public-key.gpg] https://download.eclipse.org/zenoh/debian-repo/ /" \
      | sudo tee /etc/apt/sources.list.d/zenoh.list >/dev/null

    sudo apt update
}


echo "[1/6] Install base/RMW packages"
sudo apt update
mapfile -t PKGS < <(grep -Ev '^[[:space:]]*(#|$)' "$SCRIPT_DIR/requirements.txt")
sudo apt install -y "${PKGS[@]}"

echo "[2/6] Add Eclipse Zenoh repository"
add_zenoh_repo

echo "[3/6] Install Zenoh 1.9.0 components"
sudo apt install -y     zenoh=1.9.0     zenoh-bridge-ros2dds=1.9.0     --allow-downgrades

echo "[4/6] Hold Zenoh versions"
sudo apt-mark hold zenoh zenoh-bridge-ros2dds

echo "[5/6] Verify RMW packages"
source /opt/ros/jazzy/setup.bash
ros2 pkg prefix rmw_cyclonedds_cpp
ros2 pkg prefix rmw_fastrtps_cpp

echo "[6/6] Verify Zenoh"
zenohd --version
zenoh-bridge-ros2dds --version

echo
echo "Main PC installation complete."
echo "Next: copy/review bashrc_main.conf in ~/.bashrc, then source ~/.bashrc"
