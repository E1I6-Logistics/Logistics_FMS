# 타입 힌트 지연 평가 기능 사용
from __future__ import annotations

# Robot 데이터 객체 및 사전 변환 기능 사용
from dataclasses import (
    asdict,
    dataclass,
    field,
)

# Robot 상태 갱신 시간 관리 기능 사용
from datetime import datetime
# 선택적 상태값 표현 기능 사용
from typing import Optional


# Robot 상태 저장용 데이터 클래스 생성
@dataclass
# Robot 한 대의 실제 상태와 FMS 관리 상태 저장 기능
class Robot:

    # ========================================================
    # 식별
    # ========================================================

    # Robot 고유 ID 사용
    robot_id: str

    # ========================================================
    # 통신 상태
    # ========================================================

    # FMS 연결 상태 기본값 OFFLINE 설정
    connection_state: str = "OFFLINE"

    # 마지막 상태 수신 시간 관리
    last_update: Optional[
        datetime
    ] = None

    # ========================================================
    # FMS 전체 상태
    # ========================================================

    # FMS 기준 Robot 전체 상태 기본값 OFFLINE 설정
    status: str = "OFFLINE"

    # ========================================================
    # 위치
    #
    # AMCL 수신 시:
    # map 기준 위치
    #
    # AMCL 수신 전:
    # odom fallback
    # ========================================================

    # FMS에서 사용할 Map 기준 X 위치 기본값 설정
    x: float = 0.0
    # FMS에서 사용할 Map 기준 Y 위치 기본값 설정
    y: float = 0.0
    # FMS에서 사용할 Robot 방향 기본값 설정
    yaw: float = 0.0

    # 현재 위치 정보 출처 관리
    pose_source: str = "NONE"

    # AMCL Map 위치 수신 여부 관리
    map_pose_received: bool = False

    # ========================================================
    # Odom
    # ========================================================

    # Odom 기준 X 위치 저장
    odom_x: float = 0.0
    # Odom 기준 Y 위치 저장
    odom_y: float = 0.0
    # Odom 기준 Yaw 저장
    odom_yaw: float = 0.0

    # Robot 직선 속도 저장
    linear_velocity: float = 0.0
    # Robot 각속도 저장
    angular_velocity: float = 0.0

    # ========================================================
    # Battery
    # ========================================================

    # 0 ~ 100 %
    # 배터리 잔량 백분율 저장
    battery: Optional[
        float
    ] = None

    # 배터리 전압 저장
    battery_voltage: Optional[
        float
    ] = None

    # 배터리 전류 저장
    battery_current: Optional[
        float
    ] = None

    # 배터리 충전 상태 기본값 설정
    battery_status: str = "UNKNOWN"

    # ========================================================
    # Navigation
    # ========================================================

    # Nav2 주행 상태 기본값 IDLE 설정
    navigation_state: str = "IDLE"

    # Nav2 Goal 도착 여부 관리
    goal_reached: bool = False

    # Nav2 Goal까지 남은 거리 저장
    distance_remaining: Optional[
        float
    ] = None

    # ========================================================
    # Safety / Error
    # ========================================================

    # 비상정지 상태 관리
    emergency_stop: bool = False

    # 현재 Robot 오류 코드 저장
    error_code: Optional[
        str
    ] = None

    # 현재 Robot 오류 상세 메시지 저장
    error_message: Optional[
        str
    ] = None

    # ========================================================
    # TurtleBot3 SensorState
    # ========================================================

    # TurtleBot3 Bumper 상태 저장
    bumper: int = 0

    # TurtleBot3 Cliff 센서값 저장
    cliff: float = 0.0
    # TurtleBot3 Sonar 센서값 저장
    sonar: float = 0.0
    # TurtleBot3 조도 센서값 저장
    illumination: float = 0.0

    # TurtleBot3 LED 상태 저장
    led: int = 0
    # TurtleBot3 Button 상태 저장
    button: int = 0

    # TurtleBot3 Motor Torque 상태 저장
    torque: bool = False

    # 왼쪽 Wheel Encoder 값 저장
    left_encoder: int = 0
    # 오른쪽 Wheel Encoder 값 저장
    right_encoder: int = 0

    # TurtleBot3 SensorState 배터리 값 저장
    sensor_battery: float = 0.0

    # ========================================================
    # Route Graph
    # FMS에서 관리
    # ========================================================

    # 현재 Route Graph Node 정보 관리
    current_node: Optional[
        str
    ] = None

    # 현재 이동 중인 Route Graph Edge 정보 관리
    current_edge: Optional[
        str
    ] = None

    # 다음 이동 대상 Node 정보 관리
    next_node: Optional[
        str
    ] = None

    # 현재 작업 최종 목적 Node 정보 관리
    goal_node: Optional[
        str
    ] = None

    # 현재 확정된 전체 이동 경로 목록 생성
    path: list[str] = field(
        default_factory=list
    )

    # 재경로 구분용 Path Version 관리
    path_version: int = 0

    # ========================================================
    # Resource
    # FMS에서 관리
    # ========================================================

    # 현재 점유 중인 Node 정보 관리
    occupied_node: Optional[
        str
    ] = None

    # 현재 점유 중인 Edge 정보 관리
    occupied_edge: Optional[
        str
    ] = None

    # 다음 이동용 예약 Node 정보 관리
    reserved_node: Optional[
        str
    ] = None

    # 다음 이동용 예약 Edge 정보 관리
    reserved_edge: Optional[
        str
    ] = None

    # ========================================================
    # Task
    # ========================================================

    # 현재 수행 중인 Task ID 관리
    task_id: Optional[
        str
    ] = None

    # 작업 및 이동 우선순위 관리
    priority: int = 0

    # ========================================================
    # FMS Action
    # ========================================================

    # 현재 FMS 결정 Action 상태 관리
    current_action: str = "NONE"

    # WAIT 상태 원인 정보 관리
    wait_reason: Optional[
        str
    ] = None

    # ========================================================
    # JSON 변환
    # ========================================================

    # Robot 객체를 API 및 JSON 사용 가능한 사전으로 변환 기능
    def to_dict(
        self,
    ) -> dict:

        # dataclass 전체 상태를 사전으로 변환
        data = asdict(
            self
        )

        # datetime 값을 ISO 문자열 형식으로 변환
        if self.last_update is not None:

            data[
                "last_update"
            ] = (
                self.last_update
                .isoformat()
            )

        return data