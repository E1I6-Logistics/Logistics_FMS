# 타입 힌트 지연 평가 기능 사용
from __future__ import annotations

# 운영체제 환경변수 사용
import os

# 파일 및 디렉터리 경로 처리 기능 사용
from pathlib import Path

# ============================================================
# 프로젝트 경로
# ============================================================

# 현재 파일 기준 프로젝트 루트 경로 생성
BASE_DIR = Path(__file__).resolve().parents[2]

# Map 파일 저장 디렉터리 경로 생성
MAP_DIR = BASE_DIR / "maps"

# Route Graph 파일 저장 디렉터리 경로 생성
ROUTE_DIR = BASE_DIR / "routes"

# Runtime log directory and rotation settings.
LOG_DIR = BASE_DIR / os.getenv("FMS_LOG_DIR", "logs")
LOG_LEVEL = os.getenv("FMS_LOG_LEVEL", "INFO").strip().upper()
LOG_MAX_BYTES = int(os.getenv("FMS_LOG_MAX_BYTES", str(20 * 1024 * 1024)))
LOG_BACKUP_COUNT = int(os.getenv("FMS_LOG_BACKUP_COUNT", "10"))
SLOW_REQUEST_MS = int(os.getenv("FMS_SLOW_REQUEST_MS", "1000"))
ZENOH_STALE_GRACE_SECONDS = float(os.getenv("FMS_ZENOH_STALE_GRACE_SECONDS", "6.0"))
ZENOH_REST_TIMEOUT_SECONDS = float(os.getenv("FMS_ZENOH_REST_TIMEOUT_SECONDS", "2.0"))
ZENOH_CONNECTION_CACHE_TTL_SECONDS = float(
    os.getenv("FMS_ZENOH_CONNECTION_CACHE_TTL_SECONDS", "3.0")
)

# MQTT / OMX
MQTT_ENABLED = os.getenv("FMS_MQTT_ENABLED", "true").strip().lower() in {
    "1",
    "true",
    "yes",
    "on",
}
MQTT_BROKER_HOST = os.getenv("FMS_MQTT_BROKER_HOST", "127.0.0.1")
MQTT_BROKER_PORT = int(os.getenv("FMS_MQTT_BROKER_PORT", "1883"))
MQTT_DEVICE_TIMEOUT_SECONDS = float(os.getenv("FMS_MQTT_DEVICE_TIMEOUT_SECONDS", "5.0"))

# Nav2가 성공을 반환해도 실제 위치가 목적 노드에서 이 거리보다 멀면
# 도착으로 처리하지 않는다.
ARRIVAL_TOLERANCE_METERS = float(os.getenv("FMS_ARRIVAL_TOLERANCE_METERS", "0.2"))
POSE_STALE_SECONDS = float(os.getenv("FMS_POSE_STALE_SECONDS", "3.0"))


def _parse_name_map(value: str) -> dict[str, str]:
    result = {}
    for pair in value.split(","):
        if ":" not in pair:
            continue
        key, item = pair.split(":", 1)
        if key.strip() and item.strip():
            result[key.strip()] = item.strip()
    return result


PICKUP_OMX_MAP = _parse_name_map(os.getenv("FMS_PICKUP_OMX_MAP", "5:omx1,6:omx2"))
ROBOT_WAITING_NODE_MAP = _parse_name_map(
    os.getenv("FMS_ROBOT_WAITING_NODE_MAP", "robot1:0,robot2:1,robot3:2")
)
WORKSTATION_OMX_MAP = _parse_name_map(
    os.getenv("FMS_WORKSTATION_OMX_MAP", "3:omx3,4:omx4")
)

# 0은 아직 정하지 않은 marker ID 자리표시자이다.
ARUCO_MARKER_MAP = {
    node_id: int(marker_id)
    for node_id, marker_id in _parse_name_map(
        os.getenv("FMS_ARUCO_MARKER_MAP", "3:0,4:0,5:0,6:25")
    ).items()
}


# ============================================================
# Map / Route Graph
# ============================================================

# Map YAML 파일 경로 생성
# FMS_MAP_YAML 환경변수 사용, 미설정 시 my_map.yaml 사용
MAP_YAML_PATH = MAP_DIR / os.getenv(
    "FMS_MAP_YAML",
    "my_map.yaml",
)

# Route Graph 파일 경로 생성
# FMS_ROUTE_GRAPH 환경변수 사용, 미설정 시 test.geojson 사용
ROUTE_GRAPH_PATH = ROUTE_DIR / os.getenv(
    "FMS_ROUTE_GRAPH",
    "test.geojson",
)


ROBOT_MODE = (
    os.getenv(
        "FMS_ROBOT_MODE",
        "simulation",
    )
    .strip()
    .lower()
)

if ROBOT_MODE not in {"real", "simulation"}:
    raise ValueError("FMS_ROBOT_MODE must be either 'real' or 'simulation'")

# ============================================================
# CORS
# ============================================================

# CORS 허용 Origin 목록 생성
CORS_ORIGINS = [
    origin.strip()
    for origin in os.getenv(
        "FMS_CORS_ORIGINS",
        "*",
    ).split(",")
    if origin.strip()
]
