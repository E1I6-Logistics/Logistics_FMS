# 해당 파일에서는 ROS2 메시지 타입을 import하지 않음

from __future__ import annotations

from enum import Enum


class RobotState(str, Enum):
    OFFLINE = "OFFLINE"
    INITIALIZING = "INITIALIZING"
    IDLE = "IDLE"
    TASK_ASSIGNED = "TASK_ASSIGNED"
    MOVING = "MOVING"
    WAITING = "WAITING"
    PAUSED = "PAUSED"
    DOCKING = "DOCKING"


class Robot:
    def __init__(self, robot_id: str):

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

        # FMS 상태
        self.state: RobotState = RobotState.OFFLINE

        # 작업 / 경로 상태
        self.goal_node: str | None = None
        # 현재 위치한 Route Graph Node
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

        self.x = float(x)
        self.y = float(y)
        self.yaw = float(yaw)

    def update_battery(self, percentage: float) -> None:
        self.battery = float(percentage)
