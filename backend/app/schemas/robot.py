# 타입 힌트 지연 평가 기능 사용
from __future__ import annotations

# Robot ID 형식 검증용 정규표현식 사용
import re
# Robot 상태 갱신 시간 표현 기능 사용
from datetime import datetime
# 선택적 데이터 타입 표현 기능 사용
from typing import Optional

# Robot 상태 데이터 검증용 Pydantic 모델 및 Field 사용
from pydantic import BaseModel, Field


# ============================================================
# Robot ID 변환
# ============================================================

# backend 형식 robot1, robot01 등의 Robot ID 패턴 생성
_BACKEND_ID_RE = re.compile(
    r"^robot0*([1-9][0-9]*)$",
    re.IGNORECASE,
)

# UI 형식 R-01, R01, R1 등의 Robot ID 패턴 생성
_UI_ID_RE = re.compile(
    r"^R-?0*([1-9][0-9]*)$",
    re.IGNORECASE,
)


# 다양한 Robot ID 형식을 backend 표준 형식으로 변환 기능
def normalize_robot_id(
    robot_id: str,
) -> str:
    """
    다음 형식을 모두 허용:

    robot1
    robot01
    R-01
    R01
    R1

    반환값은 항상:

    robot1
    robot2
    robot3
    """

    # 입력 Robot ID 문자열 변환 및 공백 제거
    value = str(robot_id).strip()

    # backend 형식 Robot ID 전체 패턴 일치 확인
    match = _BACKEND_ID_RE.fullmatch(value)

    if match:
        number = int(match.group(1))

        return f"robot{number}"

    # UI 형식 Robot ID 전체 패턴 일치 확인
    match = _UI_ID_RE.fullmatch(value)

    if match:
        number = int(match.group(1))

        return f"robot{number}"

    # 지원하지 않는 Robot ID 형식 예외 처리
    raise ValueError(
        f"지원하지 않는 robot_id 형식: {robot_id}"
    )


# backend Robot ID를 Frontend 표시용 ID로 변환 기능
def to_ui_robot_id(
    robot_id: str,
) -> str:

    # 입력 Robot ID를 backend 표준 형식으로 변환
    backend_id = normalize_robot_id(robot_id)

    # robot 접두사를 제거하고 숫자 ID 추출
    number = int(
        backend_id.removeprefix("robot")
    )

    # 두 자리 형식 Frontend Robot ID 생성
    return f"R-{number:02d}"


# ============================================================
# Robot 상태 Schema
# ============================================================

# Frontend 및 API용 Robot 상태 Schema 생성
class RobotState(BaseModel):

    # backend Robot ID 사용
    robot_id: str

    # Frontend 표시용 Robot ID 사용
    ui_id: str

    # Robot 기본 상태 IDLE 설정
    status: str = "IDLE"

    # 배터리 잔량 기본값 및 최소값 검증 설정
    battery: float = Field(
        default=100.0,
        ge=0.0,
    )

    # Robot X 위치 기본값 설정
    x: float = 0.0

    # Robot Y 위치 기본값 설정
    y: float = 0.0

    # Robot 방향 Yaw 기본값 설정
    yaw: float = 0.0

    # Robot 상태 갱신 시간 선택값 설정
    updated_at: Optional[datetime] = None


# ============================================================
# Dashboard telemetry event
# ============================================================

# Dashboard 전달용 Robot Telemetry 이벤트 구조 생성
class TelemetryEvent(BaseModel):

    # 이벤트 타입 telemetry 기본값 설정
    type: str = "telemetry"

    # Telemetry 이벤트에 Robot 상태 데이터 사용
    data: RobotState