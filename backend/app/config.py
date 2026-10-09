from __future__ import annotations

import os

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
# 지도와 이동 경로
# ============================================================

# 사용할 지도 설정 파일. 별도 지정이 없으면 my_map.yaml을 쓴다.
MAP_YAML_PATH = MAP_DIR / os.getenv("FMS_MAP_YAML", "my_map.yaml")

# 사용할 이동 경로 파일. 별도 지정이 없으면 test.geojson을 쓴다.
ROUTE_GRAPH_PATH = ROUTE_DIR / os.getenv("FMS_ROUTE_GRAPH", "test.geojson")

# 서버 시작 모드(main/API 분기에서 사용). 시뮬레이션 제거 후에는 FMS_ROBOT_MODE=real로 실행한다.
ROBOT_MODE = os.getenv("FMS_ROBOT_MODE", "simulation").strip().lower()
if ROBOT_MODE not in {"real", "simulation"}:
    raise ValueError("FMS_ROBOT_MODE must be either 'real' or 'simulation'")

# ============================================================
# CORS
# ============================================================

# 웹 화면이 접속할 수 있는 주소 목록
CORS_ORIGINS = [
    origin.strip() for origin in os.getenv("FMS_CORS_ORIGINS", "*").split(",") if origin.strip()
]


# ============================================================
# MQTT
# ============================================================

# MQTT 서버 주소
MQTT_BROKER_IP = os.getenv("FMS_MQTT_BROKER_IP", "127.0.0.1")

# MQTT 서버 포트
MQTT_BROKER_PORT = int(os.getenv("FMS_MQTT_BROKER_PORT", "1883"))

# ============================================================
# 실제 로봇 내비게이션 (services/real_navigation.py에서 사용)
# ============================================================

# 정상 응답에서 로봇이 잠시 누락되어도 OFFLINE으로 확정하지 않는 시간.
ZENOH_MISSING_GRACE_S = float(os.getenv("FMS_ZENOH_MISSING_GRACE_S", "5.0"))

# 실제 로봇이 움직일 것으로 예상하는 속도(m/s). 예약 시간을 계산할 때 쓴다.
# 기본값은 0.12이며 Nav2 주행 속도를 직접 변경하지 않는다.
# 실측 평균속도보다 낮추면 예약이 길어지고, 높이면 예약 충돌 위험이 커진다.
REAL_NAVIGATION_SPEED_MPS = float(os.getenv("FMS_REAL_NAVIGATION_SPEED_MPS", "0.12"))

# 지점과 통로의 예약 시간 앞뒤에 더하는 여유 시간(초).
# 시간 오차가 크면 늘리되 다른 로봇의 대기 시간이 길어진다.
REAL_RESERVATION_MARGIN_S = float(os.getenv("FMS_REAL_RESERVATION_MARGIN_S", "1.5"))

# 로봇이 지난 지점이나 통로의 예약을 풀기 전에 확인하는 최소 거리(m).
# 로봇 반경(현재 burger.yaml의 0.1m)에 위치 오차 여유 0.1m를 더한 기본값이다.
# 실제 외형 반경·AMCL 오차가 더 크면 늘린다. 낮추면 로봇 몸체가 통로에 남은 채 예약이 풀릴 수 있다.
REAL_RESERVATION_CLEARANCE_M = float(os.getenv("FMS_REAL_RESERVATION_CLEARANCE_M", "0.2"))

# 목적지에 도착했다고 볼 수 있는 최대 거리(m).
# 기본값 0.15m. 늘리면 목적지 오도착도 허용하므로 Nav2 최종 정확도 실측 후 조정한다.
REAL_ARRIVAL_DISTANCE_M = float(os.getenv("FMS_REAL_ARRIVAL_DISTANCE_M", "0.15"))

# 로봇 위치를 지도상의 지점이나 통로에 맞춰 볼 때 허용하는 거리(m).
# 먼저 0.15m로 판정하고 실패하면 기본값 0.2m로 재시도한다.
# 가까운 Edge가 겹치면 현재/다음 경로 Edge가 단독 최단거리일 때만 확정한다.
# 최종 목적지 도착 기준은 별도 0.15m이며, 받은 위치값은 바꾸지 않는다.
# 낮추면 위치 미확정 정지가 늘고, 높이면 인접 통로를 혼동하기 쉬워진다.
REAL_OCCUPANCY_TOLERANCE_M = float(os.getenv("FMS_REAL_OCCUPANCY_TOLERANCE_M", "0.2"))

# 중간 지점을 지난 직후 위치가 이전 통로에 잡히더라도,
# 공통 지점에서 이 거리(m) 안이면 현재 통로를 계속 점유한 것으로 본다.
# 기본값 0.2m. 코너에서 잘못 멈추면 실제 위치 오차를 확인한 뒤 조금씩 올리고,
# 다른 통로까지 허용될 우려가 있으면 낮춘다. 일반 점유 허용 거리보다 크게 적용하지 않는다.
REAL_ROUTE_TRANSITION_DISTANCE_M = float(os.getenv("FMS_REAL_ROUTE_TRANSITION_DISTANCE_M", "0.2"))

# 충전 지점 바깥쪽에 있는 로봇을 해당 지점에 있다고 볼 최대 거리(m).
# 새 로봇의 위치가 아직 오지 않았을 때는 담당 충전 지점을 보호한다.
# 실제 충전 위치가 더 멀면 값을 늘릴 수 있지만 이웃 지점과 겹치지 않아야 한다.
REAL_DOCK_OCCUPANCY_TOLERANCE_M = float(os.getenv("FMS_REAL_DOCK_OCCUPANCY_TOLERANCE_M", "0.25"))

# 새 로봇의 첫 위치 정보를 기다리며 담당 충전 지점을 보호하는 시간(초).
# 시간이 지나도 위치를 모르면 안전을 위해 주행을 멈춘다.
# 실제 첫 위치 정보가 더 늦게 올 때만 늘린다.
REAL_INITIAL_POSE_TIMEOUT_S = float(os.getenv("FMS_REAL_INITIAL_POSE_TIMEOUT_S", "3.0"))

# 마지막으로 받은 로봇 위치를 믿을 수 있는 시간(초).
# 값을 늘리면 잠깐의 통신 지연은 견디지만 위치를 잃은 사실도 늦게 알게 된다.
REAL_POSE_TIMEOUT_S = float(os.getenv("FMS_REAL_POSE_TIMEOUT_S", "2.0"))

# 예약과 주행 상태를 다시 확인하는 간격(초). 기본값 0.2초.
# 늘리면 확인 횟수가 줄지만 짧은 통로에서의 정지 판단이 늦어질 수 있다.
REAL_NAVIGATION_INTERVAL_S = float(os.getenv("FMS_REAL_NAVIGATION_INTERVAL_S", "0.2"))

# Nav2가 성공을 알린 뒤 실제 위치 정보가 도착하기를 기다리는 시간(초).
# 도착 허용 거리(기존 0.15m)를 넓히는 값은 아니다.
# Nav2 결과와 위치 정보가 오는 시각의 차이가 크면 늘릴 수 있지만 다음 작업도 늦어진다.
REAL_ARRIVAL_CONFIRM_TIMEOUT_S = float(os.getenv("FMS_REAL_ARRIVAL_CONFIRM_TIMEOUT_S", "1.0"))

# Nav2 이동 취소가 끝나기를 기다리는 시간(초). 초과하면 일시정지 상태로 둔다.
# 기존 예약과 이동 명령은 유지하며, 종료 확인 전에는 새 이동 명령을 보내지 않는다.
# 종료 응답이 느릴 때만 늘린다. 시간을 넘었다는 이유만으로 예약을 풀지 않는다.
REAL_CANCEL_TIMEOUT_S = float(os.getenv("FMS_REAL_CANCEL_TIMEOUT_S", "5.0"))

# 잘못된 단위/범위로 실제 실행 주기나 예약 계산이 동작하지 않도록 시작 시 확인한다.
import math

for _name in (
    "ZENOH_MISSING_GRACE_S",
    "REAL_NAVIGATION_SPEED_MPS",
    "REAL_RESERVATION_MARGIN_S",
    "REAL_RESERVATION_CLEARANCE_M",
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
