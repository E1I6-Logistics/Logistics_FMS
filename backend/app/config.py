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
ZENOH_STALE_GRACE_SECONDS = float(
    os.getenv("FMS_ZENOH_STALE_GRACE_SECONDS", "6.0")
)
ZENOH_REST_TIMEOUT_SECONDS = float(
    os.getenv("FMS_ZENOH_REST_TIMEOUT_SECONDS", "2.0")
)
ZENOH_CONNECTION_CACHE_TTL_SECONDS = float(
    os.getenv("FMS_ZENOH_CONNECTION_CACHE_TTL_SECONDS", "3.0")
)


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
