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
BASE_DIR = (
    Path(__file__)
    .resolve()
    .parents[2]
)

# Map 파일 저장 디렉터리 경로 생성
MAP_DIR = (
    BASE_DIR / "maps"
)

# Route Graph 파일 저장 디렉터리 경로 생성
ROUTE_DIR = (
    BASE_DIR / "routes"
)


# ============================================================
# Map / Route Graph
# ============================================================

# Map YAML 파일 경로 생성
# FMS_MAP_YAML 환경변수 사용, 미설정 시 my_map.yaml 사용
MAP_YAML_PATH = (
    MAP_DIR
    / os.getenv(
        "FMS_MAP_YAML",
        "my_map.yaml",
    )
)

# Route Graph 파일 경로 생성
# FMS_ROUTE_GRAPH 환경변수 사용, 미설정 시 test.geojson 사용
ROUTE_GRAPH_PATH = (
    ROUTE_DIR
    / os.getenv(
        "FMS_ROUTE_GRAPH",
        "test.geojson",
    )
)


# ============================================================
# Robot
# ============================================================

# FMS에서 관리할 Robot 개수 설정
ROBOT_COUNT = int(
    os.getenv(
        "FMS_ROBOT_COUNT",
        "3",
    )
)

# Robot OFFLINE 판단 시간 설정
ROBOT_OFFLINE_TIMEOUT_SEC = float(
    os.getenv(
        "FMS_ROBOT_OFFLINE_TIMEOUT_SEC",
        "3.0",
    )
)

ROBOT_MODE = os.getenv(
    "FMS_ROBOT_MODE",
    "simulation",
).strip().lower()

if ROBOT_MODE not in {"real", "simulation"}:
    raise ValueError(
        "FMS_ROBOT_MODE must be either 'real' or 'simulation'"
    )

TELEMETRY_TIMEOUT_SECONDS = float(
    os.getenv("FMS_TELEMETRY_TIMEOUT_SECONDS", "5.0")
)

# ============================================================
# 수동주행 최대 속도
# ============================================================

# 수동주행 최대 직선 속도 설정
CMD_VEL_MAX_LINEAR = float(
    os.getenv(
        "FMS_CMD_VEL_MAX_LINEAR",
        "0.5",
    )
)

# 수동주행 최대 각속도 설정
CMD_VEL_MAX_ANGULAR = float(
    os.getenv(
        "FMS_CMD_VEL_MAX_ANGULAR",
        "2.0",
    )
)


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


# ============================================================
# 알려진 로봇 IP
# ============================================================

# Robot IP와 robot_id 매핑 정보 관리
KNOWN_DEVICES = {
    "10.10.141.226": "robot1",
    "10.10.141.246": "robot2",
    "10.10.141.221": "robot3",
}