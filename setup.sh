#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="$HOME/venv/robot"
ROS_DISTRO="jazzy"
NODE_VERSION="20.20.2"

echo "============================================================"
echo " Logistics_FMS 개발환경 자동 설치"
echo "============================================================"

if [[ "$(uname -m)" != "x86_64" ]]; then
  echo "[ERROR] x86_64 환경이 아닙니다."
  exit 1
fi

if ! grep -q 'VERSION_ID="24.04"' /etc/os-release; then
  echo "[ERROR] Ubuntu 24.04가 아닙니다."
  cat /etc/os-release
  exit 1
fi

echo "[1/8] Ubuntu 기본 패키지"
sudo apt update
sudo apt install -y software-properties-common curl wget git ca-certificates gnupg lsb-release locales build-essential cmake gcc g++ python3 python3-pip python3-venv python3-dev

echo "[2/8] ROS 2 Jazzy 저장소"
sudo locale-gen en_US en_US.UTF-8
sudo update-locale LC_ALL=en_US.UTF-8 LANG=en_US.UTF-8
sudo add-apt-repository universe -y

if ! dpkg -s ros2-apt-source >/dev/null 2>&1; then
  ROS_APT_SOURCE_VERSION="$(curl -s https://api.github.com/repos/ros-infrastructure/ros-apt-source/releases/latest | grep -F '"tag_name"' | awk -F'"' '{print $4}')"
  [[ -n "$ROS_APT_SOURCE_VERSION" ]] || { echo "[ERROR] ros2-apt-source 버전 확인 실패"; exit 1; }
  curl -L -o /tmp/ros2-apt-source.deb "https://github.com/ros-infrastructure/ros-apt-source/releases/download/${ROS_APT_SOURCE_VERSION}/ros2-apt-source_${ROS_APT_SOURCE_VERSION}.$(. /etc/os-release && echo "$VERSION_CODENAME")_all.deb"
  sudo dpkg -i /tmp/ros2-apt-source.deb
fi

sudo apt update
sudo apt upgrade -y

echo "[3/8] ROS 2 + Nav2 패키지"
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
  python3-colcon-common-extensions \
  python3-rosdep \
  python3-vcstool

if ! grep -Fq "source /opt/ros/jazzy/setup.bash" "$HOME/.bashrc"; then
  echo "source /opt/ros/jazzy/setup.bash" >> "$HOME/.bashrc"
fi
source /opt/ros/jazzy/setup.bash

if [[ ! -f /etc/ros/rosdep/sources.list.d/20-default.list ]]; then
  sudo rosdep init || true
fi
rosdep update || true

echo "[4/8] Docker"
sudo apt install -y docker.io docker-compose-v2
sudo systemctl enable --now docker
if ! id -nG "$USER" | grep -qw docker; then
  sudo usermod -aG docker "$USER"
  DOCKER_GROUP_CHANGED=1
else
  DOCKER_GROUP_CHANGED=0
fi

echo "[5/8] Node.js $NODE_VERSION"
export NVM_DIR="$HOME/.nvm"
if [[ ! -s "$NVM_DIR/nvm.sh" ]]; then
  curl -o- https://raw.githubusercontent.com/nvm-sh/nvm/v0.40.3/install.sh | bash
fi
source "$NVM_DIR/nvm.sh"
nvm install "$NODE_VERSION"
nvm alias default "$NODE_VERSION"
nvm use "$NODE_VERSION"

echo "[6/8] Python venv"
mkdir -p "$HOME/venv"
if [[ ! -d "$VENV_DIR" ]]; then
  python3 -m venv --system-site-packages "$VENV_DIR"
fi
source "$VENV_DIR/bin/activate"
python -m pip install --upgrade pip==26.2.1
python -m pip install -r "$PROJECT_DIR/backend/requirements.txt"

echo "[7/8] Frontend"
cd "$PROJECT_DIR/frontend"
if [[ -f package-lock.json ]]; then
  npm ci
else
  npm install
fi
cd "$PROJECT_DIR"

echo "[8/8] .env"
if [[ ! -f "$PROJECT_DIR/.env" && -f "$PROJECT_DIR/.env.example" ]]; then
  cp "$PROJECT_DIR/.env.example" "$PROJECT_DIR/.env"
fi

echo "============================================================"
echo " 설치 완료"
echo "============================================================"
echo "VENV=$VENV_DIR"
echo "Node=$(node --version)"
echo "npm=$(npm --version)"
echo "ROS_DISTRO=$ROS_DISTRO"
if [[ "$DOCKER_GROUP_CHANGED" -eq 1 ]]; then
  echo "[중요] 로그아웃 후 다시 로그인해야 Docker 그룹 권한이 적용됩니다."
fi
