#!/usr/bin/env bash

set -euo pipefail


# ============================================================
# Logistics_FMS Development Environment Setup
#
# Supported:
#   - Ubuntu 24.04 x86_64
#   - Ubuntu 24.04 aarch64 / NVIDIA Jetson
# ============================================================

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

VENV_DIR="$HOME/venv/robot"

ROS_DISTRO="jazzy"
NODE_VERSION="20.20.2"

ARCH="$(uname -m)"


# ============================================================
# Platform Detection
# ============================================================

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
        echo "[ERROR] Unsupported architecture: $ARCH"
        exit 1
        ;;

esac


# ============================================================
# OS Check
# ============================================================

if ! grep -q 'VERSION_ID="24.04"' /etc/os-release; then

    echo "[ERROR] Ubuntu 24.04 is required."

    cat /etc/os-release

    exit 1

fi


echo "============================================================"
echo " Logistics_FMS Environment Setup"
echo "============================================================"
echo "Platform : $PLATFORM"
echo "Arch     : $ARCH"
echo "ROS      : $ROS_DISTRO"
echo "Node     : $NODE_VERSION"
echo "Project  : $PROJECT_DIR"
echo "============================================================"


# ============================================================
# 1. Ubuntu Base Packages
# ============================================================

echo "[1/9] Ubuntu base packages"

sudo apt update

sudo apt install -y \
    software-properties-common \
    curl \
    wget \
    git \
    ca-certificates \
    gnupg \
    lsb-release \
    locales \
    build-essential \
    cmake \
    gcc \
    g++ \
    python3 \
    python3-pip \
    python3-venv \
    python3-dev


# ============================================================
# Jetson Safety
# ============================================================

if [ "$PLATFORM" = "JETSON" ]; then

    echo "[INFO] Jetson detected."
    echo "[INFO] Full apt upgrade is skipped to protect JetPack/NVIDIA stack."

else

    echo "[INFO] Updating installed Ubuntu packages."

    sudo apt upgrade -y

fi


# ============================================================
# 2. ROS 2 Jazzy Repository
# ============================================================

echo "[2/9] ROS 2 Jazzy repository"

sudo locale-gen en_US en_US.UTF-8

sudo update-locale \
    LC_ALL=en_US.UTF-8 \
    LANG=en_US.UTF-8

sudo add-apt-repository universe -y


if ! dpkg -s ros2-apt-source >/dev/null 2>&1; then

    ROS_APT_SOURCE_VERSION="$(
        curl -fsSL \
            https://api.github.com/repos/ros-infrastructure/ros-apt-source/releases/latest \
            | awk -F'"' '/tag_name/ {print $4; exit}'
    )"

    if [ -z "$ROS_APT_SOURCE_VERSION" ]; then
        echo "[ERROR] Failed to determine ros2-apt-source version."
        exit 1
    fi

    UBUNTU_CODENAME="$(
        . /etc/os-release
        echo "$VERSION_CODENAME"
    )"

    curl -fsSL \
        -o /tmp/ros2-apt-source.deb \
        "https://github.com/ros-infrastructure/ros-apt-source/releases/download/${ROS_APT_SOURCE_VERSION}/ros2-apt-source_${ROS_APT_SOURCE_VERSION}.${UBUNTU_CODENAME}_all.deb"

    sudo dpkg -i /tmp/ros2-apt-source.deb

fi


sudo apt update


# ============================================================
# 3. ROS 2 / Navigation
# ============================================================

echo "[3/9] ROS 2 Jazzy packages"

sudo apt install -y \
    ros-jazzy-desktop \
    ros-jazzy-navigation2 \
    ros-jazzy-nav2-bringup \
    ros-jazzy-robot-localization \
    ros-jazzy-tf2-tools \
    ros-jazzy-slam-toolbox \
    ros-jazzy-rosbridge-server \
    ros-jazzy-teleop-twist-keyboard \
    ros-jazzy-cv-bridge \
    ros-jazzy-ros-gz-sim \
    ros-jazzy-ros-gz-bridge \
    ros-jazzy-rmw-cyclonedds-cpp \
    ros-jazzy-rmw-fastrtps-cpp \
    ros-jazzy-turtlebot3-msgs \
    python3-colcon-common-extensions \
    python3-rosdep \
    python3-vcstool


source /opt/ros/jazzy/setup.bash


if [ ! -f /etc/ros/rosdep/sources.list.d/20-default.list ]; then
    sudo rosdep init || true
fi

rosdep update || true


# ============================================================
# 4. Docker
# ============================================================

echo "[4/9] Docker"

sudo apt install -y \
    docker.io \
    docker-compose-v2

sudo systemctl enable --now docker


DOCKER_GROUP_CHANGED=0

if ! id -nG "$USER" | grep -qw docker; then

    sudo usermod -aG docker "$USER"

    DOCKER_GROUP_CHANGED=1

fi


# ============================================================
# 5. Node.js / NVM
# ============================================================

echo "[5/9] Node.js $NODE_VERSION"

export NVM_DIR="$HOME/.nvm"


if [ ! -s "$NVM_DIR/nvm.sh" ]; then

    curl -fsSL \
        https://raw.githubusercontent.com/nvm-sh/nvm/v0.40.3/install.sh \
        | bash

fi


source "$NVM_DIR/nvm.sh"

nvm install "$NODE_VERSION"

nvm alias default "$NODE_VERSION"

nvm use "$NODE_VERSION"


# ============================================================
# 6. Python Virtual Environment
# ============================================================

echo "[6/9] Python virtual environment"

mkdir -p "$HOME/venv"


if [ ! -d "$VENV_DIR" ]; then

    python3 -m venv \
        --system-site-packages \
        "$VENV_DIR"

fi


source "$VENV_DIR/bin/activate"

python -m pip install --upgrade pip

python -m pip install \
    -r "$PROJECT_DIR/backend/requirements.txt"


# ============================================================
# 7. Main / Zenoh
# ============================================================

echo "[7/9] Main FMS / Zenoh"

chmod +x "$PROJECT_DIR/scripts/main/install_main.sh"

"$PROJECT_DIR/scripts/main/install_main.sh"


# ============================================================
# 8. Frontend
# ============================================================

echo "[8/9] Frontend"

cd "$PROJECT_DIR/frontend"


if [ -f package-lock.json ]; then

    npm ci

else

    npm install

fi


cd "$PROJECT_DIR"


# ============================================================
# 9. AX Shell Environment
# ============================================================

echo "[9/9] Shell environment"

cp \
    "$PROJECT_DIR/scripts/main/bashrc_main.conf" \
    "$HOME/.axbashrc"


if ! grep -Fq 'source ~/.axbashrc' "$HOME/.bashrc"; then

    echo "" >> "$HOME/.bashrc"

    echo '# Logistics_FMS environment' \
        >> "$HOME/.bashrc"

    echo 'source ~/.axbashrc' \
        >> "$HOME/.bashrc"

fi


# ============================================================
# Executable Permission
# ============================================================

chmod +x \
    "$PROJECT_DIR/start_fms.sh" \
    "$PROJECT_DIR/stop_fms.sh" \
    "$PROJECT_DIR/scripts/verify_env.sh"


# ============================================================
# Result
# ============================================================

echo ""
echo "============================================================"
echo " Installation Complete"
echo "============================================================"
echo "Platform : $PLATFORM"
echo "Arch     : $ARCH"
echo "VENV     : $VENV_DIR"
echo "Node     : $(node --version)"
echo "npm      : $(npm --version)"
echo "ROS      : $ROS_DISTRO"
echo "============================================================"

if [ "$DOCKER_GROUP_CHANGED" -eq 1 ]; then

    echo ""
    echo "[IMPORTANT]"
    echo "Docker group membership was changed."
    echo "Log out and log in again before using Docker without sudo."

fi

echo ""
echo "Open a new terminal or run:"
echo ""
echo "  source ~/.axbashrc"
echo ""
echo "Then verify:"
echo ""
echo "  cd $PROJECT_DIR"
echo "  ./scripts/verify_env.sh"
