echo "===== OS ====="
lsb_release -a 2>/dev/null || cat /etc/os-release

echo
echo "===== KERNEL ====="
uname -a

echo
echo "===== PYTHON ====="
python3 --version
which python3
pip3 --version

echo
echo "===== VENV / PIP PACKAGES ====="
if [ -d "venv" ]; then
  source ~/venv/robot/bin/activate
  echo "VENV_ACTIVE=$VIRTUAL_ENV"
  python --version
  pip --version
  pip freeze
  deactivate
else
  echo ".venv 없음"
fi

echo
echo "===== ROS2 ====="
which ros2
printenv ROS_DISTRO
ros2 --version 2>/dev/null || true

echo
echo "===== ROS2 PACKAGES ====="
dpkg -l | grep -E "ros-jazzy|ros-humble|ros-rolling" | awk '{print $2}' | sort

echo
echo "===== NODE / NPM ====="
node --version
npm --version
which node
which npm

echo
echo "===== FRONTEND PACKAGE ====="
if [ -f "frontend/package.json" ]; then
  cat frontend/package.json
else
  echo "frontend/package.json 없음"
fi

echo
echo "===== DOCKER ====="
docker --version
docker compose version

echo
echo "===== GIT ====="
git --version

echo
echo "===== PROJECT TREE ====="
find . -maxdepth 3 -type f | sort

echo
echo "===== APT DEV PACKAGES ====="
dpkg -l | grep -E "python3-venv|python3-pip|python3-dev|build-essential|git|curl|docker|nodejs|npm" | awk '{print $2, $3}'
