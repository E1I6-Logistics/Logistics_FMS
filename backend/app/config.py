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

# real_navigation의 TrafficManager 예약 시간 계산용 예상 속도(m/s).
# 기본값은 0.12이며 Nav2 주행 속도를 직접 변경하지 않는다.
# 실측 평균속도보다 낮추면 예약이 길어지고, 높이면 예약 충돌 위험이 커진다.
REAL_NAVIGATION_SPEED_MPS = float(os.getenv("FMS_REAL_NAVIGATION_SPEED_MPS", "0.12"))

# 실제용 TrafficManager가 노드/통로 예약 앞뒤에 적용하는 여유 시간(초).
# services/real_navigation.py가 TrafficManager를 생성할 때 사용한다.
# 시간 오차가 크면 늘리되 다른 로봇의 대기 시간이 길어진다.
REAL_RESERVATION_MARGIN_S = float(os.getenv("FMS_REAL_RESERVATION_MARGIN_S", "1.5"))

# ros2/ros_gateway.py와 services/real_navigation.py의 실제 최종 도착 거리(m).
# 기본값 0.15m. 늘리면 목적지 오도착도 허용하므로 Nav2 최종 정확도 실측 후 조정한다.
REAL_ARRIVAL_DISTANCE_M = float(os.getenv("FMS_REAL_ARRIVAL_DISTANCE_M", "0.15"))

# real_navigation에서 실제 Pose를 Route Graph의 Node/Edge에 대응시킬 때의 허용 거리(m).
# 먼저 0.15m로 판정하고 실패하면 기본값 0.2m로 재시도한다.
# 가까운 Edge가 겹치면 현재/다음 경로 Edge가 단독 최단거리일 때만 확정한다.
# 최종 목적지 도착 허용 거리는 별도 0.15m이며 원본 Pose는 변경하지 않는다.
# 낮추면 위치 미확정 정지가 늘고, 높이면 인접 통로를 혼동하기 쉬워진다.
REAL_OCCUPANCY_TOLERANCE_M = float(os.getenv("FMS_REAL_OCCUPANCY_TOLERANCE_M", "0.2"))

# services/real_navigation.py: 중간 Node 통과 직후 Pose가 직전 Edge에 다시 잡힐 때,
# 공유 Node로부터 이 거리(m) 안이면 실제 Edge 점유를 유지하며 주행을 계속한다.
# 기본값 0.2m. 코너에서 오정지가 나면 실제 Pose 오차를 확인한 뒤 조금씩 올리고,
# 다른 통로까지 허용될 우려가 있으면 낮춘다. 일반 점유 허용 거리보다 크게 적용하지 않는다.
REAL_ROUTE_TRANSITION_DISTANCE_M = float(os.getenv("FMS_REAL_ROUTE_TRANSITION_DISTANCE_M", "0.2"))

# real_navigation에서 담당 충전 Node의 바깥쪽 도킹 위치를 해당 Node 점유로 보는 최대 거리(m).
# 일반 Node/Edge 점유 허용 거리는 바꾸지 않으며, 등록 직후 Pose가 없는 동안에는 담당 충전 Node를 보호한다.
# 실제 도킹 위치가 담당 Node에서 더 멀면 늘리되 이웃 Node와 겹치지 않게 한다.
REAL_DOCK_OCCUPANCY_TOLERANCE_M = float(os.getenv("FMS_REAL_DOCK_OCCUPANCY_TOLERANCE_M", "0.25"))

# real_navigation에서 새로 연결된 Robot의 첫 Pose를 기다리며 담당 충전 Node를 임시 점유하는 최대 시간(초).
# 이 시간이 지나도 Pose가 없으면 위치 미확인으로 기존 주행 안전 정지 정책을 적용한다.
# 로봇 등록 후 첫 Pose 지연이 이 값보다 길 때만 늘린다.
REAL_INITIAL_POSE_TIMEOUT_S = float(os.getenv("FMS_REAL_INITIAL_POSE_TIMEOUT_S", "3.0"))

# 실제 실행부가 Robot.pose_received_at의 최신성을 확인하는 최대 경과 시간(초).
# Pose 수신 주기보다 충분히 길게 두되, 늘릴수록 위치 상실 감지가 늦어진다.
REAL_POSE_TIMEOUT_S = float(os.getenv("FMS_REAL_POSE_TIMEOUT_S", "2.0"))

# main.run_real_navigation에서 예약 재시도/구간 실행 상태를 확인하는 주기(초). 기본값 0.2초.
# 늘리면 부하가 줄지만 짧은 Edge의 진입·정지 판단이 늦어질 수 있다.
REAL_NAVIGATION_INTERVAL_S = float(os.getenv("FMS_REAL_NAVIGATION_INTERVAL_S", "0.2"))

# real_navigation: Nav2 성공 직후 늦게 수신되는 위치를 확인하는 최대 대기 시간(초).
# 도착 허용 거리(기존 0.15m)를 넓히는 값은 아니다.
# Nav2 결과와 AMCL Pose 수신 시간차가 길면 늘리며, 후속 작업 시작은 그만큼 늦어진다.
REAL_ARRIVAL_CONFIRM_TIMEOUT_S = float(os.getenv("FMS_REAL_ARRIVAL_CONFIRM_TIMEOUT_S", "1.0"))

# real_navigation: Nav2 취소 종료를 기다리는 최대 시간(초). 초과 시 PAUSED로 두고
# 기존 예약/Goal을 유지한다. 실제 종료 확인 없이 새 Goal을 보내지 않는다.
# Action 종료 응답이 느리면 늘리되, 실제로 취소되지 않은 Goal을 강제로 해제하지 않는다.
REAL_CANCEL_TIMEOUT_S = float(os.getenv("FMS_REAL_CANCEL_TIMEOUT_S", "5.0"))

# 잘못된 단위/범위로 실제 실행 주기나 예약 계산이 동작하지 않도록 시작 시 확인한다.
import math

for _name in (
    "REAL_NAVIGATION_SPEED_MPS",
    "REAL_RESERVATION_MARGIN_S",
    "REAL_ARRIVAL_DISTANCE_M",
    "REAL_OCCUPANCY_TOLERANCE_M",
    "REAL_ROUTE_TRANSITION_DISTANCE_M",
    "REAL_DOCK_OCCUPANCY_TOLERANCE_M",
    "REAL_INITIAL_POSE_TIMEOUT_S",
    "REAL_POSE_TIMEOUT_S",
    "REAL_NAVIGATION_INTERVAL_S",
    "REAL_ARRIVAL_CONFIRM_TIMEOUT_S",
    "REAL_CANCEL_TIMEOUT_S",
):
    if not math.isfinite(globals()[_name]) or globals()[_name] <= 0:
        raise ValueError(f"{_name} must be a finite positive value")
