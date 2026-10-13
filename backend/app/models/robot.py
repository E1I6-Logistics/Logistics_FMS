# 해당 파일에서는 ROS2 메시지 타입을 import하지 않음

from __future__ import annotations

from enum import Enum

from threading import RLock
from time import monotonic, strftime


class RobotState(str, Enum):
    OFFLINE = "OFFLINE"
    INITIALIZING = "INITIALIZING"
    IDLE = "IDLE"
    TASK_ASSIGNED = "TASK_ASSIGNED"
    MOVING = "MOVING"
    NAVIGATING = "NAVIGATING"
    WAITING = "WAITING"
    PAUSED = "PAUSED"
    DOCKING = "DOCKING"
    EMERGENCY_STOP = "EMERGENCY_STOP"


class NavigationType(str, Enum):
    GOAL = "goal"
    RETURN = "return"
    CHARGING = "charging"

PAUSE_REASON_MESSAGES = {
    "reconnected_with_active_work": "연결이 복구됐지만 이전 작업이 남아 있어 자동 재개하지 않았습니다.",
    "after_stop_failed": "정지 확인 후 다음 작업을 시작하지 못했습니다.",
    "cancel_send_failed": "Nav2 취소 요청을 전송하지 못했습니다.",
    "cancel_timeout": "Nav2 취소의 최종 결과를 제한 시간 안에 확인하지 못했습니다.",
    "cancel_cleanup_waiting_for_occupancy": "취소 후 현재 점유 위치를 확인하지 못했습니다.",
    "concession_interrupted": "다른 로봇에게 양보하는 과정이 중단되었습니다.",
    "concession_failed": "다른 로봇에게 양보한 뒤 경로를 복구하지 못했습니다.",
    "hold_node_passed": "정지해야 할 노드를 이미 통과했습니다.",
    "hold_failed": "안전 정지 위치를 확보하지 못했습니다.",
    "navigation_update_failed": "Nav2 경로를 갱신하지 못했습니다.",
    "current_segment_occupied": "현재 이동 구간을 다른 로봇이 점유하고 있습니다.",
    "goal_send_failed": "Nav2에 이동 목표를 전송하지 못했습니다.",
    "navigation_request_failed": "이동 요청을 시작하지 못했습니다.",
    "navigation_execution_error": "Nav2 실행 중 통신 또는 처리 오류가 발생했습니다.",
    "navigation_result_offline": "Nav2 결과 수신 시 로봇 연결이 끊겨 있었습니다.",
    "navigation_result_failed": "Nav2 주행이 실패 상태로 종료되었습니다.",
    "route_progress_unconfirmed": "계획된 중간 노드 통과를 확인하지 못했습니다.",
    "arrival_interrupted_offline": "목적지 확인 중 로봇 연결이 끊겼습니다.",
    "arrival_interrupted": "목적지 도착 확인 과정이 중단되었습니다.",
    "arrival_failed": "목적지 도착 위치를 확인하지 못했습니다.",
    "state_sync_failed": "측정 위치와 경로 상태를 동기화하지 못했습니다.",
    "omx_next_request_failed": "OMX 종료 후 다음 요청을 시작하지 못했습니다.",
    "precision_dock_goal_send_failed": "정밀 도킹 목표를 전송하지 못했습니다.",
    "precision_dock_failed": "정밀 도킹 작업이 실패했습니다.",
    "aruco_goal_send_failed": "ArUco 정렬 목표를 전송하지 못했습니다.",
    "aruco_alignment_failed": "ArUco 정렬 작업이 실패했습니다.",
    "navigation_aborted": "Nav2가 주행을 중단했습니다.",
    "order_items_missing_for_node": "현재 위치에서 처리할 주문 품목을 찾지 못했습니다.",
    "mqtt_job_send_failed": "OMX에 작업 명령을 전송하지 못했습니다.",
    "omx_job_failed": "OMX 작업 결과가 실패로 반환되었습니다.",
    "charging_station_missing": "로봇에 할당된 충전 위치가 없습니다.",
    "station_return_failed": "주문 완료 후 대기 위치로 복귀하지 못했습니다.",
    "next_destination_failed": "다음 주문 목적지로 이동을 시작하지 못했습니다.",
    "pose_stale_route_protected": "로봇 위치 정보가 갱신되지 않아 기존 경로와 점유를 보호한 상태로 일시정지했습니다.",
    "robot_offline_route_protected": "로봇 연결이 끊겨 기존 경로와 점유를 보호한 상태로 일시정지했습니다.",
    "robot_offline": "로봇 연결이 끊겨 현재 위치와 점유를 확인할 수 없습니다.",
    "pose_stale_or_invalid": "로봇 위치 정보가 오래됐거나 올바르지 않습니다.",
    "route_mismatch_protected": "측정 위치와 계획 경로가 일치하지 않아 기존 경로를 보호했습니다.",
    "occupancy_or_route_mismatch": "로봇의 측정 위치와 점유 또는 계획 경로가 일치하지 않습니다.",
}

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
        # 프로그램 및 테스트에서 비교하는 고정 코드
        self.pause_reason_code: str | None = None
        # 사용자 화면에 표시하는 한글 설명
        self.pause_reason: str | None = None

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
        was_connected = self.connected
        previous_state = self.state
        self.connected = connected

        if connected:
            if self.state == RobotState.OFFLINE:
                # 진행 중이던 이동/주문은 연결 복구만으로 IDLE 또는 자동 재출발시키지 않는다.
                active = (self.route is not None or self.navigation_type is not None
                          or self.order_id is not None)
                if active:
                    self.pause("reconnected_with_active_work")
                elif self.pose_received_at is None:
                    self.state = RobotState.INITIALIZING
                else:
                    self.state = RobotState.IDLE
        elif self.state != RobotState.EMERGENCY_STOP:
            # 연결 여부는 connected에 남기고 비상정지는 명시적 해제 전까지 유지한다.
            self.state = RobotState.OFFLINE

        if was_connected != self.connected or previous_state != self.state:
            if self.state != RobotState.PAUSED:
                self.pause_reason_code = None
                self.pause_reason = None
            level = "INFO" if connected else "WARN"
            print(f"[{strftime('%Y-%m-%d %H:%M:%S')}] [{level}] [ROBOT CONNECTION] robot={self.robot_id} "
                  f"connected={was_connected}->{self.connected} "
                  f"state={previous_state.value}->{self.state.value} "
                  f"order_id={self.order_id}", flush=True)

    def set_state(self, state: RobotState) -> None:
        if state == RobotState.PAUSED:
            raise ValueError(
                "PAUSED 상태는 set_state() 대신 pause(reason_code, detail)를 사용해야 합니다."
            )

        with self._lock:
            previous_state = self.state

            self.state = state
            self.pause_reason_code = None
            self.pause_reason = None

            if previous_state != state:
                level = (
                    "WARN"
                    if state in (RobotState.EMERGENCY_STOP, RobotState.OFFLINE)
                    else "INFO"
                )
                print(
                    f"[{strftime('%Y-%m-%d %H:%M:%S')}] [{level}] [ROBOT STATE] "
                    f"robot={self.robot_id} "
                    f"state={previous_state.value}->{state.value} "
                    f"connected={self.connected} order_id={self.order_id}",
                    flush=True,
                )

    def pause(self, reason_code: str, detail: str | None = None) -> None:
        if not reason_code:
            raise ValueError("PAUSED 상태에는 reason_code가 필요합니다.")

        with self._lock:
            previous_state = self.state
            message = PAUSE_REASON_MESSAGES.get(
                reason_code,
                f"알 수 없는 원인으로 일시정지했습니다. 원인 코드: {reason_code}",
            )

            self.state = RobotState.PAUSED
            self.pause_reason_code = reason_code
            self.pause_reason = (
                message
                if not detail
                else f"{message} 상세: {detail}"
            )

            print(
                f"[{strftime('%Y-%m-%d %H:%M:%S')}] [WARN] [ROBOT STATE] "
                f"robot={self.robot_id} "
                f"state={previous_state.value}->{self.state.value} "
                f"reason_code={reason_code} detail={detail!r} "
                f"connected={self.connected} order_id={self.order_id}",
                flush=True,
            )

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
        self.set_state(RobotState.TASK_ASSIGNED)

    def clear_order(self) -> None:
        self.order_id = None
        self.order_items = {}
        self.order_total_quantity = 0
        self.order_pickup_nodes = []
        self.order_workstation_node = None
        self.order_pickup_index = 0

    def update_battery(self, percentage: float) -> None:
        self.battery = float(percentage)
