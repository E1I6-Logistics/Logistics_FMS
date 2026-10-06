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
    EMERGENCY_STOP = "EMERGENCY_STOP"


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
        # 현재 계획된 경로
        self.route = None

        # 현재 위치한 Route Graph Node. 구간 사이에서는 None
        self.current_node = None

        # 현재 점유 중인 Node (ex. "3")
        self.occupied_node: str | None = None
        # 현재 이동 중인 Edge의 도착 Node (ex. "4")
        self.next_node: str | None = None
        # 현재 점유 중인 Edge (ex. "edge_3_4")
        self.occupied_edge: str | None = None
        # 현재 occupied_edge 주행 완료 후 다음으로 점유할 Edge (ex. "edge_4_5")
        self.next_edge: str | None = None

        # 예약 상태
        self.reserved_nodes: list[str] = []
        self.reserved_edges: list[str] = []

        # 현재 배정된 주문
        self.order_id: str | None = None
        self.order_items: dict[str, int] = {}
        self.order_total_quantity: int = 0
        self.order_workstation_node: str | None = None
        self.order_pickup_nodes: list[str] = []

        # 현재 진행 중인 Pickup 순서
        self.order_pickup_index: int = 0

    def set_connected(self, connected: bool) -> None:
        self.connected = connected

        if connected:
            if self.state == RobotState.OFFLINE:
                # 진행 중이던 이동/주문은 연결 복구만으로 IDLE 또는 자동 재출발시키지 않는다.
                active = (self.route is not None or self.navigation_type is not None
                          or self.order_id is not None)
                self.state = RobotState.PAUSED if active else RobotState.IDLE
        elif self.state != RobotState.EMERGENCY_STOP:
            # 연결 여부는 connected에 남기고 비상정지는 명시적 해제 전까지 유지한다.
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

    def assign_order(
        self,
        order_id: str,
        items: dict[str, int],
        total_quantity: int,
        pickup_nodes: list[str],
        workstation_node: str,
    ) -> None:

        self.order_id = order_id
        self.order_items = items
        self.order_total_quantity = total_quantity
        self.order_pickup_nodes = pickup_nodes
        self.order_workstation_node = workstation_node
        self.order_pickup_index = 0  # 첫 번째 Pickup부터 시작

        self.state = RobotState.TASK_ASSIGNED

    def clear_order(self) -> None:
        self.order_id = None
        self.order_items = {}
        self.order_total_quantity = 0
        self.order_pickup_nodes = []
        self.order_workstation_node = None
        self.order_pickup_index = 0

    def update_battery(self, percentage: float) -> None:
        self.battery = float(percentage)
