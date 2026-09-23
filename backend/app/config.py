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


ROBOT_MODE = os.getenv(
    "FMS_ROBOT_MODE",
    "simulation",
).strip().lower()

if ROBOT_MODE not in {"real", "simulation"}:
    raise ValueError(
        "FMS_ROBOT_MODE must be either 'real' or 'simulation'"
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
