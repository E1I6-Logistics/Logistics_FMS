#!/usr/bin/env bash
set +e
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="$HOME/venv/robot"

echo "===== OS ====="
grep -E '^(NAME|VERSION|VERSION_ID)=' /etc/os-release

echo "===== ROS 2 ====="
source /opt/ros/jazzy/setup.bash 2>/dev/null
echo "ROS_DISTRO=$ROS_DISTRO"
which ros2
ros2 pkg prefix nav2_bringup
ros2 pkg prefix nav2_route
ros2 pkg prefix robot_localization

echo "===== PYTHON ====="
source "$VENV_DIR/bin/activate"
python --version
python - <<'PY'
import fastapi, uvicorn, asyncpg, zenoh, yaml, PIL, pydantic, rclpy
from geometry_msgs.msg import Pose
from std_msgs.msg import String
print("Python imports: OK")
PY

echo "===== NODE ====="
export NVM_DIR="$HOME/.nvm"
source "$NVM_DIR/nvm.sh" 2>/dev/null
node --version
npm --version

echo "===== DOCKER ====="
docker --version
docker compose version

echo "===== FRONTEND ====="
test -d "$PROJECT_DIR/frontend/node_modules" && echo "node_modules: OK" || echo "node_modules: MISSING"
