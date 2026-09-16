from __future__ import annotations

import os
from pathlib import Path


# ============================================================
# 프로젝트 경로
# ============================================================

# 현재 파일:
# Logistics_FMS/backend/app/config.py
#
# parents[0] -> backend/app
# parents[1] -> backend
# parents[2] -> Logistics_FMS
BASE_DIR = Path(__file__).resolve().parents[2]

MAP_DIR = BASE_DIR / "maps"
ROUTE_DIR = BASE_DIR / "routes"


# ============================================================
# Map / Route Graph
# ============================================================

MAP_YAML_PATH = MAP_DIR / os.getenv(
    "FMS_MAP_YAML",
    "my_map.yaml",
)

ROUTE_GRAPH_PATH = ROUTE_DIR / os.getenv(
    "FMS_ROUTE_GRAPH",
    "test.geojson",
)


# ============================================================
# Zenoh
# ============================================================

ZENOH_ENDPOINT = os.getenv(
    "FMS_ZENOH_ENDPOINT",
    "tcp/127.0.0.1:7447",
)

ZENOH_ROBOT_COUNT = int(
    os.getenv("FMS_ROBOT_COUNT", "3")
)


# ============================================================
# 수동주행 최대 속도
# ============================================================

CMD_VEL_MAX_LINEAR = float(
    os.getenv("FMS_CMD_VEL_MAX_LINEAR", "0.5")
)

CMD_VEL_MAX_ANGULAR = float(
    os.getenv("FMS_CMD_VEL_MAX_ANGULAR", "2.0")
)


# ============================================================
# CORS
# ============================================================

CORS_ORIGINS = [
    origin.strip()
    for origin in os.getenv(
        "FMS_CORS_ORIGINS",
        "*",
    ).split(",")
    if origin.strip()
]


# ============================================================
# 알려진 로봇 IP
# ============================================================

KNOWN_DEVICES = {
    "10.10.141.226": "robot1",
    "10.10.141.246": "robot2",
    "10.10.141.221": "robot3",
}