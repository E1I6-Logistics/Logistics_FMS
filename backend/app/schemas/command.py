# 타입 힌트 지연 평가 기능 사용
from __future__ import annotations

# 여러 자료형 허용을 위한 Union 타입 사용
from typing import Union

# API 요청 및 응답 데이터 검증용 Pydantic 모델 사용
from pydantic import BaseModel


# ============================================================
# 좌표 기반 이동
# ============================================================

# 좌표 기반 이동 요청 데이터 구조 생성
class GoalCoordinateRequest(BaseModel):

    # 이동 대상 Robot ID 사용
    robot_id: str

    # 목표 X 좌표 사용
    target_x: float

    # 목표 Y 좌표 사용
    target_y: float


# ============================================================
# Node 기반 이동
# ============================================================

# Route Graph Node 기반 이동 요청 데이터 구조 생성
class GoalNodeRequest(BaseModel):

    robot_id: str

    # 숫자 또는 문자열 형식 Node ID 사용
    node_id: Union[int, str]


# ============================================================
# 정지
# ============================================================

# Robot 정지 요청 데이터 구조 생성
class StopRequest(BaseModel):

    robot_id: str


# ============================================================
# cmd_vel
# ============================================================

# 수동 주행 cmd_vel 요청 데이터 구조 생성
class CmdVelRequest(BaseModel):

    robot_id: str

    # 직선 속도 기본값 설정
    linear_x: float = 0.0

    # 회전 각속도 기본값 설정
    angular_z: float = 0.0


# ============================================================
# 연결 차단 / 허용
# ============================================================

# 장치 연결 차단 및 허용 요청 데이터 구조 생성
class DevicePayload(BaseModel):

    # 대상 장치 IP 주소 사용
    ip: str


# ============================================================
# 공통 명령 응답
# ============================================================

# 공통 명령 응답 데이터 구조 생성
class CommandResponse(BaseModel):

    # 명령 처리 상태 사용
    status: str

    robot_id: str

    # Frontend 표시용 Robot ID 사용
    ui_id: str

    # 명령에 사용된 ROS Topic 정보 사용
    topic: str

    # 추가 응답 메시지 기본값 설정
    message: str = ""