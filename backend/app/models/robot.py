# 해당 파일에서는 ROS2 메시지 타입을 import하지 않음

from __future__ import annotations

from enum import Enum

from threading import RLock
from time import monotonic


class RobotState(str, Enum):
    OFFLINE = "OFFLINE"
    INITIALIZING = "INITIALIZING"
    IDLE = "IDLE"
    TASK_ASSIGNED = "TASK_ASSIGNED"
    MOVING = "MOVING"
    WAITING = "WAITING"
    PAUSED = "PAUSED"
    DOCKING = "DOCKING"


class NavigationType(str, Enum):
    GOAL = "goal"
    RETURN = "return"
    CHARGING = "charging"


class Robot:
    def __init__(self, robot_id: str):

        # ROS 콜백과 API 사이의 상태 읽기/쓰기 보호
        self._lock = RLock()

        # 현재 로봇이 수행 중인 navigation type. None이면 navigation 중 아님
        self.navigation_type: NavigationType | None = None

        # 로봇 식별자
        self.robot_id = robot_id

        # 연결 상태
        self.connected = False

        # 위치 상태
        self.x: float | None = None
        self.y: float | None = None
        self.yaw: float | None = None

        # 배터리 상태
        self.battery: float | None = None

        # 현재 동작 상태
        self.state: RobotState = RobotState.OFFLINE

        # 마지막 AMCL 수신 시각. monotonic() 기준 초 단위. 위치 최신성 검사용
        # monotonic() - 내부 경과 시간 비교. 시스템 시간 변경의 영향을 받지 않음
        self.pose_received_at: float | None = None

        # 현재 관리 중인 주행 요청 식별자. 이전 목표의 늦은 피드백 또는 결과가 새 상태를 변경하지 않도록 사용
        self.navigation_id: str | None = None

        # 현재 요청된 최종 목적지
        self.goal_node: str | None = None
        # 현재 위치한 Route Graph Node. 구간 사이에서는 None
        self.current_node = None
        # 현재 계획된 경로
        self.route = None

        # 점유 상태
        self.occupied_node: str | None = None
        self.occupied_edge: str | None = None

        # 예약 상태
        self.reserved_nodes: list[str] = []
        self.reserved_edges: list[str] = []

    def set_connected(self, connected: bool) -> None:
        self.connected = connected

        if connected:
            if self.state == RobotState.OFFLINE:
                self.state = RobotState.IDLE
        else:
            self.state = RobotState.OFFLINE

    def set_state(self, state: RobotState) -> None:
        self.state = state

    def update_pose(self, x: float, y: float, yaw: float) -> None:
        with self._lock:
            self.x = float(x)
            self.y = float(y)
            self.yaw = float(yaw)
            self.pose_received_at = (
                monotonic()
            )  # FMS가 위치를 저장한 시각. AMCL 메시지의 측정 시간이나 웹 전송 시각과는 별개

    def update_battery(self, percentage: float) -> None:
        self.battery = float(percentage)
