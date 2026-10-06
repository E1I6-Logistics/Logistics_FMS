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


# ============================================================
# Map / Route Graph
# ============================================================

# Map YAML 파일 경로 생성
# FMS_MAP_YAML 환경변수 사용, 미설정 시 my_map.yaml 사용
MAP_YAML_PATH = MAP_DIR / os.getenv("FMS_MAP_YAML", "my_map.yaml")

# Route Graph 파일 경로 생성
# FMS_ROUTE_GRAPH 환경변수 사용, 미설정 시 test.geojson 사용
ROUTE_GRAPH_PATH = ROUTE_DIR / os.getenv("FMS_ROUTE_GRAPH", "test.geojson")

# 서버 시작 모드(main/API 분기에서 사용). 시뮬레이션 제거 후에는 FMS_ROBOT_MODE=real로 실행한다.
ROBOT_MODE = os.getenv("FMS_ROBOT_MODE", "simulation").strip().lower()
if ROBOT_MODE not in {"real", "simulation"}:
    raise ValueError("FMS_ROBOT_MODE must be either 'real' or 'simulation'")

# ============================================================
# CORS
# ============================================================

# CORS 허용 Origin 목록 생성
CORS_ORIGINS = [
    origin.strip() for origin in os.getenv("FMS_CORS_ORIGINS", "*").split(",") if origin.strip()
]


# ============================================================
# MQTT
# ============================================================

# MQTT Broker 주소
MQTT_BROKER_IP = os.getenv("FMS_MQTT_BROKER_IP", "127.0.0.1")

# MQTT Broker 포트
MQTT_BROKER_PORT = int(os.getenv("FMS_MQTT_BROKER_PORT", "1883"))

# ============================================================
# 실제 로봇 내비게이션 (services/real_navigation.py에서 사용)
# ============================================================

# TrafficManager 예약 시간 계산용 예상 속도(m/s). 기존 실제 A*의 0.025 유지.
# Nav2 속도를 변경하는 값이 아니며, 실제 주행 속도에 맞춰 설정한다.
REAL_NAVIGATION_SPEED_MPS = float(os.getenv("FMS_REAL_NAVIGATION_SPEED_MPS", "0.025"))

# 실제용 TrafficManager가 노드/통로 예약 앞뒤에 적용하는 여유 시간(초).
REAL_RESERVATION_MARGIN_S = float(os.getenv("FMS_REAL_RESERVATION_MARGIN_S", "0.2"))

# 실제 수신 위치를 occupancy.locate_occupancy에 전달할 때의 허용 거리(m).
# 기존 실제 도착 허용 거리 0.15m를 기본값으로 사용하며 원본 좌표는 변경하지 않는다.
REAL_OCCUPANCY_TOLERANCE_M = float(os.getenv("FMS_REAL_OCCUPANCY_TOLERANCE_M", "0.15"))

# 실제 실행부가 Robot.pose_received_at의 최신성을 확인하는 최대 경과 시간(초).
REAL_POSE_TIMEOUT_S = float(os.getenv("FMS_REAL_POSE_TIMEOUT_S", "2.0"))

# main.run_real_navigation에서 예약 재시도/구간 실행 상태를 확인하는 주기(초).
REAL_NAVIGATION_INTERVAL_S = float(os.getenv("FMS_REAL_NAVIGATION_INTERVAL_S", "0.1"))

# 잘못된 단위/범위로 실제 실행 주기나 예약 계산이 동작하지 않도록 시작 시 확인한다.
import math
for _name in ("REAL_NAVIGATION_SPEED_MPS", "REAL_RESERVATION_MARGIN_S",
              "REAL_OCCUPANCY_TOLERANCE_M", "REAL_POSE_TIMEOUT_S", "REAL_NAVIGATION_INTERVAL_S"):
    if not math.isfinite(globals()[_name]) or globals()[_name] <= 0:
        raise ValueError(f"{_name} must be a finite positive value")
