from __future__ import annotations

import logging
from threading import RLock
from uuid import uuid4

from ..config import (
    ARUCO_MARKER_MAP,
    PICKUP_OMX_MAP,
    ROBOT_WAITING_NODE_MAP,
    WORKSTATION_OMX_MAP,
)
from ..models.robot import RobotState
from ..schemas.robot import normalize_robot_id
from .fleet_manager import fleet_manager
from .mqtt_manager import mqtt_manager
from .route_graph import get_node


logger = logging.getLogger("fms.order")

ITEM_PICKUP_NODE = {"A": "5", "B": "5", "C": "6", "D": "6"}
ACTIVE_ORDER_STATES = {"PROCESSING", "WAITING_OMX"}


class OrderService:
    def __init__(self) -> None:
        self._lock = RLock()
        # job_id -> 작업 정보
        self._omx_jobs: dict[str, dict] = {}

    def create_order(
        self,
        robot_id: str,
        items: dict[str, int],
        workstation_node: str,
    ) -> dict:
        backend_robot_id = normalize_robot_id(robot_id)
        robot = fleet_manager.get_robot(backend_robot_id)

        if robot is None:
            raise ValueError(f"Robot을 찾을 수 없습니다: {backend_robot_id}")
        if not robot.connected:
            raise ValueError(f"Robot이 연결되어 있지 않습니다: {backend_robot_id}")
        if robot.state != RobotState.IDLE:
            raise ValueError("로봇이 대기 상태일 때만 주문을 시작할 수 있습니다.")
        if robot.order_status in ACTIVE_ORDER_STATES:
            raise ValueError(f"이미 처리 중인 주문이 있습니다: {robot.order_id}")

        clean_items = {name: int(quantity) for name, quantity in items.items()}
        total_quantity = sum(clean_items.values())
        if total_quantity < 1 or total_quantity > 5:
            raise ValueError("주문 수량은 합계 1개 이상 5개 이하여야 합니다.")

        workstation_node = str(workstation_node)
        if workstation_node not in {"3", "4"}:
            raise ValueError("작업대 Node는 3 또는 4여야 합니다.")
        get_node(workstation_node)

        pickup_nodes: list[str] = []
        for item, quantity in clean_items.items():
            if quantity <= 0:
                continue
            pickup_node = ITEM_PICKUP_NODE.get(item)
            if pickup_node is None:
                raise ValueError(f"픽업 Node가 지정되지 않은 물품입니다: {item}")
            if pickup_node not in pickup_nodes:
                pickup_nodes.append(pickup_node)

        if not pickup_nodes:
            raise ValueError("주문된 물품이 없습니다.")

        with self._lock:
            robot.order_id = f"ORD-{uuid4().hex[:8].upper()}"
            robot.order_items = clean_items
            robot.pickup_nodes = pickup_nodes
            robot.current_pickup_node = pickup_nodes[0]
            robot.workstation_node = workstation_node
            robot.order_status = "PROCESSING"
            robot.order_phase = "TO_PICKUP"
            robot.loaded_count = 0

        logger.info(
            "event=order_created order_id=%s robot_id=%s pickup_nodes=%s workstation=%s",
            robot.order_id,
            backend_robot_id,
            pickup_nodes,
            workstation_node,
        )
        return self.snapshot(backend_robot_id)

    def snapshot(self, robot_id: str) -> dict:
        robot = fleet_manager.get_robot(robot_id)
        if robot is None:
            raise ValueError(f"Robot을 찾을 수 없습니다: {robot_id}")
        return {
            "order_id": robot.order_id,
            "robot_id": robot.robot_id,
            "items": robot.order_items.copy(),
            "total_quantity": sum(robot.order_items.values()),
            "pickup_nodes": robot.pickup_nodes.copy(),
            "workstation_node": robot.workstation_node,
            "destination_node": robot.current_pickup_node,
            "status": robot.order_status,
            "phase": robot.order_phase,
            "loaded_count": robot.loaded_count,
        }

    def mark_dispatch_failed(self, robot_id: str, error: Exception) -> None:
        self._fail_order(robot_id, str(error), phase="DISPATCH_FAILED")

    def fail_active_order(self, robot_id: str, phase: str, message: str) -> None:
        robot = fleet_manager.get_robot(robot_id)
        if robot is None or robot.order_status not in ACTIVE_ORDER_STATES:
            return
        self._fail_order(robot_id, message, phase=phase)

    def cancel_active_order(
        self, robot_id: str, reason: str = "emergency_stop"
    ) -> None:
        robot = fleet_manager.get_robot(robot_id)
        if robot is None or robot.order_status not in ACTIVE_ORDER_STATES:
            return
        robot.order_status = "CANCELED"
        robot.order_phase = "CANCELED"
        robot.current_pickup_node = None
        self._remove_robot_jobs(robot_id)
        logger.warning(
            "event=order_canceled order_id=%s robot_id=%s reason=%s",
            robot.order_id,
            robot_id,
            reason,
        )

    def handle_arrival(self, robot_id: str, node_id: str) -> bool:
        """실제 좌표까지 검증된 도착을 다음 주문 단계로 연결한다."""
        robot = fleet_manager.get_robot(robot_id)
        if robot is None or robot.order_status not in ACTIVE_ORDER_STATES:
            return False

        node_id = str(node_id)
        if robot.order_phase == "TO_PICKUP" and node_id == robot.current_pickup_node:
            self._start_alignment(robot_id, node_id, "PICKUP")
            return True

        if robot.order_phase == "TO_WORKSTATION" and node_id == robot.workstation_node:
            self._start_alignment(robot_id, node_id, "WORKSTATION")
            return True

        if robot.order_phase == "TO_WAITING":
            expected_node = ROBOT_WAITING_NODE_MAP.get(robot_id)
            if node_id == expected_node:
                robot.order_status = "COMPLETED"
                robot.order_phase = "DONE"
                robot.current_pickup_node = None
                robot.loaded_count = 0
                robot.set_state(RobotState.IDLE)
                logger.info(
                    "event=order_completed order_id=%s robot_id=%s",
                    robot.order_id,
                    robot_id,
                )
                return True

        return False

    def _start_alignment(self, robot_id: str, node_id: str, purpose: str) -> None:
        robot = fleet_manager.get_robot(robot_id)
        if robot is None:
            return

        marker_id = ARUCO_MARKER_MAP.get(node_id, 0)
        if marker_id <= 0:
            self._fail_order(
                robot_id,
                f"Node {node_id}의 ArUco marker ID가 아직 설정되지 않았습니다.",
                phase="ARUCO_MARKER_NOT_CONFIGURED",
            )
            return

        robot.order_phase = f"ALIGNING_{purpose}"
        robot.set_state(RobotState.ALIGNING)

        from ..ros2.ros_gateway import ros_gateway

        try:
            ros_gateway.align_with_aruco(robot_id, node_id, marker_id)
        except (ValueError, RuntimeError) as exc:
            self._fail_order(robot_id, str(exc), phase="ARUCO_DISPATCH_FAILED")

    def handle_alignment_result(
        self, robot_id: str, node_id: str, success: bool, details: dict
    ) -> bool:
        robot = fleet_manager.get_robot(robot_id)
        if robot is None or robot.order_status not in ACTIVE_ORDER_STATES:
            return False

        if not success:
            result_code = details.get("result_code", "unknown")
            self._fail_order(
                robot_id,
                f"ArUco 정렬 실패(result_code={result_code})",
                phase="ARUCO_FAILED",
            )
            return True

        if robot.order_phase == "ALIGNING_PICKUP" and node_id == robot.current_pickup_node:
            self._start_load_job(robot_id, node_id)
            return True
        elif robot.order_phase == "ALIGNING_WORKSTATION" and node_id == robot.workstation_node:
            self._start_unload_job(robot_id, node_id)
            return True
        return False

    def _start_load_job(self, robot_id: str, pickup_node: str) -> None:
        robot = fleet_manager.get_robot(robot_id)
        if robot is None:
            return
        omx_id = PICKUP_OMX_MAP.get(pickup_node)
        if omx_id is None:
            self._fail_order(robot_id, f"Node {pickup_node}에 OMX가 지정되지 않았습니다.")
            return

        items = {
            item: quantity
            for item, quantity in robot.order_items.items()
            if quantity > 0 and ITEM_PICKUP_NODE.get(item) == pickup_node
        }
        self._send_omx_job(robot_id, pickup_node, omx_id, "LOAD", items)

    def _start_unload_job(self, robot_id: str, workstation_node: str) -> None:
        robot = fleet_manager.get_robot(robot_id)
        if robot is None:
            return
        omx_id = WORKSTATION_OMX_MAP.get(workstation_node)
        if omx_id is None:
            self._fail_order(
                robot_id, f"작업대 Node {workstation_node}에 OMX가 지정되지 않았습니다."
            )
            return
        self._send_omx_job(
            robot_id,
            workstation_node,
            omx_id,
            "UNLOAD",
            robot.order_items.copy(),
        )

    def _send_omx_job(
        self,
        robot_id: str,
        node_id: str,
        omx_id: str,
        operation: str,
        items: dict[str, int],
    ) -> None:
        robot = fleet_manager.get_robot(robot_id)
        if robot is None:
            return

        total_count = sum(items.values()) if operation == "LOAD" else robot.loaded_count
        if total_count <= 0:
            self._fail_order(robot_id, "OMX에 전달할 수량이 없습니다.")
            return

        job_id = f"{robot.order_id}-{operation}-N{node_id}"
        try:
            mqtt_manager.send_command(
                omx_id,
                job_id,
                items,
                operation=operation,
                total_count=total_count,
            )
        except RuntimeError as exc:
            self._fail_order(robot_id, str(exc), phase="WAITING_OMX_CONNECTION")
            return

        with self._lock:
            self._omx_jobs[job_id] = {
                "robot_id": robot_id,
                "node_id": node_id,
                "operation": operation,
                "base_count": robot.loaded_count,
                "total_count": total_count,
            }
            robot.order_status = "WAITING_OMX"
            robot.order_phase = "LOADING" if operation == "LOAD" else "UNLOADING"
            robot.set_state(RobotState.WAITING)

        logger.info(
            "event=order_waiting_omx order_id=%s robot_id=%s omx_id=%s "
            "operation=%s total_count=%s",
            robot.order_id,
            robot_id,
            omx_id,
            operation,
            total_count,
        )

    def handle_omx_progress(self, omx, data: dict) -> None:
        job_id = str(data.get("job_id", ""))
        with self._lock:
            job = self._omx_jobs.get(job_id)
        if job is None:
            return

        robot = fleet_manager.get_robot(job["robot_id"])
        if robot is None or robot.order_status != "WAITING_OMX":
            return

        try:
            current = max(0, min(int(data.get("current", 0)), job["total_count"]))
        except (TypeError, ValueError):
            logger.warning("event=omx_progress_invalid job_id=%s data=%s", job_id, data)
            return

        if job["operation"] == "LOAD":
            robot.loaded_count = job["base_count"] + current
        else:
            robot.loaded_count = max(0, job["base_count"] - current)

        logger.info(
            "event=robot_load_updated robot_id=%s operation=%s loaded_count=%s",
            robot.robot_id,
            job["operation"],
            robot.loaded_count,
        )

    def handle_omx_result(self, omx, data: dict) -> None:
        job_id = str(data.get("job_id", ""))
        with self._lock:
            job = self._omx_jobs.pop(job_id, None)
        if job is None:
            logger.warning(
                "event=order_unknown_omx_result omx_id=%s job_id=%s",
                omx.robot_id,
                job_id,
            )
            return

        robot_id = job["robot_id"]
        robot = fleet_manager.get_robot(robot_id)
        if robot is None:
            return
        if robot.order_status != "WAITING_OMX":
            logger.warning("event=order_late_omx_result robot_id=%s job_id=%s", robot_id, job_id)
            return
        if not data.get("success", False):
            self._fail_order(robot_id, data.get("message") or "OMX 작업 실패")
            return

        robot.order_status = "PROCESSING"
        if job["operation"] == "LOAD":
            robot.loaded_count = job["base_count"] + job["total_count"]
            completed_node = job["node_id"]
            robot.pickup_nodes = [
                node for node in robot.pickup_nodes if node != completed_node
            ]
            if robot.pickup_nodes:
                robot.current_pickup_node = robot.pickup_nodes[0]
                robot.order_phase = "TO_PICKUP"
                destination = robot.current_pickup_node
            else:
                robot.current_pickup_node = None
                robot.order_phase = "TO_WORKSTATION"
                destination = robot.workstation_node
        else:
            robot.loaded_count = 0
            robot.order_phase = "TO_WAITING"
            destination = ROBOT_WAITING_NODE_MAP.get(robot_id)

        if destination is None:
            self._fail_order(robot_id, "다음 목적지가 없습니다.")
            return
        self._navigate(robot_id, destination)

    def _navigate(self, robot_id: str, node_id: str) -> None:
        from ..ros2.ros_gateway import ros_gateway

        try:
            ros_gateway.navigate_to_node(robot_id, node_id, preserve_order=True)
        except (KeyError, ValueError, RuntimeError) as exc:
            self._fail_order(robot_id, str(exc))

    def _fail_order(self, robot_id: str, message: str, phase: str = "FAILED") -> None:
        robot = fleet_manager.get_robot(robot_id)
        if robot is None:
            return
        robot.order_status = "FAILED"
        robot.order_phase = phase
        self._remove_robot_jobs(robot_id)
        robot.set_state(RobotState.PAUSED)
        logger.warning(
            "event=order_failed order_id=%s robot_id=%s phase=%s error=%s",
            robot.order_id,
            robot_id,
            phase,
            message,
        )

    def _remove_robot_jobs(self, robot_id: str) -> None:
        with self._lock:
            stale_jobs = [
                job_id
                for job_id, job in self._omx_jobs.items()
                if job["robot_id"] == robot_id
            ]
            for job_id in stale_jobs:
                self._omx_jobs.pop(job_id, None)


order_service = OrderService()
