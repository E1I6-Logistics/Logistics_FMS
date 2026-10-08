from __future__ import annotations

from typing import Any
from copy import deepcopy
from functools import wraps
from ..services.real_navigation import RealNavigation, measured_distance
from ..config import REAL_ARRIVAL_DISTANCE_M
from time import monotonic, strftime


from ..services.mqtt_manager import mqtt_manager
from ..models.robot import RobotState, NavigationType
from ..schemas.robot import normalize_robot_id, to_ui_robot_id
from ..services.fleet_manager import fleet_manager
from ..services.pathfinding import DistanceAStar
from ..services.route_graph import (
    get_node,
    load_route_graph,
    find_edge_ids,
    locate_current_node,
    find_nearest_node,
)

from action_msgs.msg import GoalStatus
import math
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .fms_ros_node import FmsRosNode

ARRIVAL_DISTANCE_THRESHOLD = REAL_ARRIVAL_DISTANCE_M

GOAL_YAWS = {
    "0": 0.0,
    "1": 0.0,
    "2": 0.0,
    "3": 0.0,
    "4": 0.0,
    "5": -math.pi / 2,
    "6": -math.pi / 2,
}

CHARGING_STATION_NODES = {
    "robot1": "0",
    "robot2": "1",
    "robot3": "2",
}

ARUCO_MARKER_IDS = {
    "6": 25,
    # "6": 28,
    "5": 24,
    # "5": 29,
    "4": 26,
    "3": 27,
}

# 작업 Node별 OMX 장비
NODE_OMX_MAP = {
    "5": "omx1",
    "6": "omx2",
    "3": "omx3",
    "4": "omx4",
}

# 작업 Node별 처리 품목
NODE_ITEM_MAP = {
    "5": ["A", "B"],
    "6": ["C", "D"],
    "3": ["A", "B", "C", "D"],
    "4": ["A", "B", "C", "D"],
}


def simplify_waypoint_nodes(node_ids):
    # 노드가 2개 이하이면 줄일 필요 없음
    if len(node_ids) <= 2:
        return node_ids.copy()

    result = [node_ids[0]]

    for index in range(1, len(node_ids) - 1):
        previous = get_node(node_ids[index - 1])
        current = get_node(node_ids[index])
        next_node = get_node(node_ids[index + 1])

        # 이전 노드 -> 현재 노드 방향
        angle1 = math.atan2(
            current["y"] - previous["y"],
            current["x"] - previous["x"],
        )

        # 현재 노드 -> 다음 노드 방향
        angle2 = math.atan2(
            next_node["y"] - current["y"],
            next_node["x"] - current["x"],
        )

        # 두 진행 방향의 차이
        angle_diff = abs(
            math.atan2(
                math.sin(angle2 - angle1),
                math.cos(angle2 - angle1),
            )
        )

        # 거의 직선이면 현재 노드를 Waypoint에서 제외
        if angle_diff < math.radians(5):
            continue

        # 방향이 바뀌는 노드는 유지
        result.append(node_ids[index])

    # 목적지는 항상 유지
    result.append(node_ids[-1])

    return result


def _navigation_locked(method):
    @wraps(method)
    def locked(self, *args, **kwargs):
        with self._navigation.lock:
            return method(self, *args, **kwargs)
    return locked


class RosGateway:
    def __init__(self) -> None:
        self._ros_node: FmsRosNode | None = None
        self._waiting_omx = {}
        self._navigation = RealNavigation(
            fleet_manager,
            lambda **kwargs: self._ros_node.send_follow_waypoints_goal(**kwargs),
            lambda *args, **kwargs: self._ros_node.cancel_follow_waypoints(*args, **kwargs),
            lambda robot_id: self.on_navigation_result(robot_id, GoalStatus.STATUS_SUCCEEDED),
            GOAL_YAWS, ARRIVAL_DISTANCE_THRESHOLD,
            station_nodes=CHARGING_STATION_NODES,
        )

    def set_ros_node(self, ros_node: FmsRosNode) -> None:
        self._ros_node = ros_node
        ros_node.navigation_lock = self._navigation.lock
        ros_node.navigation_result_callback = self._on_segment_result
        ros_node.navigation_feedback_callback = self._navigation.on_feedback
        ros_node.navigation_error_callback = self._navigation.on_execution_error
        ros_node.precision_dock_result_callback = self.on_precision_dock_result
        ros_node.aruco_align_result_callback = self.on_aruco_align_result

    def _on_segment_result(self, robot_id: str, status: int) -> None:
        self._navigation.on_result(robot_id, status == GoalStatus.STATUS_SUCCEEDED, status=status)

    def advance_navigation(self) -> None:
        self._navigation.tick()

    @_navigation_locked
    def sync_connected_robots(self, connections: list[dict]) -> None:

        if self._ros_node is None:
            raise RuntimeError("FMS ROS node is not initialized")

        # 현재 Zenoh에 연결되어 있는 로봇 ID 저장
        connected_robot_ids = []

        for connection in connections:
            if not connection.get("connected"):
                continue

            robot_id = str(connection.get("name", "")).strip()
            if not robot_id:
                continue

            connected_robot_ids.append(robot_id)
            # FMS Robot 객체 생성 또는 연결 상태 갱신
            fleet_manager.register_robot(robot_id)

            # ROS Interface 생성
            self._ros_node.register_robot(robot_id)

        # 이전에 등록됐지만 현재 Zenoh에서 보이지 않는 로봇은 OFFLINE 처리
        for robot in fleet_manager.get_all_robots():

            if robot.robot_id not in connected_robot_ids:
                fleet_manager.disconnect_robot(robot.robot_id)
                # self._ros_node.register_robot(robot_id)

    # 로봇 ID를 정규화하고 ROS 노드에 등록 여부를 확인
    def _resolve_robot_id(self, robot_id: str) -> str:
        robot_id = normalize_robot_id(robot_id)

        if self._ros_node is None:
            raise RuntimeError("ROS node is not initialized")

        if not self._ros_node.is_registered(robot_id):
            raise ValueError(f"Robot is not registered: {robot_id}")

        return robot_id

    def _validate_navigation_request(self, robot_id, node_id):
        # 기존 Goal을 취소하기 전에 입력 오류를 거절한다.
        robot = fleet_manager.get_robot(robot_id)
        if robot is None or not robot.connected:
            raise ValueError(f"Robot이 연결되어 있지 않습니다: {robot_id}")
        if robot.state == RobotState.EMERGENCY_STOP:
            raise ValueError(f"비상정지 상태입니다: {robot_id}")
        target = get_node(node_id)
        measured_distance(robot, (target["x"], target["y"]), monotonic())

    def _on_omx_terminal(self, robot_id, job_id):
        with self._navigation.lock:
            waiting = self._waiting_omx.get(robot_id)
            if waiting is None or waiting[0] != job_id:
                return
            _, callback, reason = self._waiting_omx.pop(robot_id)
            print(f"[{strftime('%H:%M:%S')}] [ROS GATEWAY OMX] robot={robot_id} "
                  f"job_id={job_id} terminal confirmed", flush=True)
            robot = fleet_manager.get_robot(robot_id)
            if callback is not None and robot is not None and robot.state != RobotState.EMERGENCY_STOP:
                try:
                    self._stop_before_navigation(robot_id, callback, reason, cancel_order=False)
                except (ValueError, RuntimeError) as exc:
                    robot.set_state(RobotState.PAUSED)
                    print(f"[{strftime('%H:%M:%S')}] [ROS GATEWAY OMX ERROR] robot={robot_id} "
                          f"next_request_failed={exc!r}", flush=True)

    def _stop_before_navigation(self, robot_id, callback, reason, *, cancel_order=True):
        """OMX·도킹·정렬·Nav2의 기존 작업 종료를 순서대로 확인한 뒤 다음 작업을 실행한다."""
        if robot_id in self._waiting_omx:
            job_id = self._waiting_omx[robot_id][0]
            self._waiting_omx[robot_id] = (job_id, callback, reason)
            print(f"[{strftime('%H:%M:%S')}] [ROS GATEWAY OMX] robot={robot_id} "
                  f"new request queued until job_id={job_id} finishes", flush=True)
            return
        robot = fleet_manager.get_robot(robot_id)
        if cancel_order and robot is not None and robot.order_id is not None:
            job_id = robot.order_id
            robot.clear_order()
            self._waiting_omx[robot_id] = (job_id, callback, reason)
            if not mqtt_manager.cancel_job(
                    job_id, callback=lambda rid=robot_id, job=job_id: self._on_omx_terminal(rid, job)):
                robot.set_state(RobotState.WAITING)
                return
            self._waiting_omx.pop(robot_id, None)
        if self._ros_node.has_active_auxiliary(robot_id):
            self._ros_node.cancel_auxiliary(
                robot_id,
                callback=lambda: self._navigation.stop(robot_id, callback, reason=reason))
        else:
            self._navigation.stop(robot_id, callback, reason=reason)

    @_navigation_locked
    def cancel_current_work(self, robot_id, callback):
        robot_id = self._resolve_robot_id(robot_id)
        robot = fleet_manager.get_robot(robot_id)
        if robot is None or not robot.connected or robot.state == RobotState.EMERGENCY_STOP:
            raise ValueError(f"새 작업을 받을 수 없는 Robot입니다: {robot_id}")
        self._stop_before_navigation(robot_id, callback, "new_order_request")

    # ROS 노드에 cmd_vel 명령을 발행하고, 응답을 반환
    @_navigation_locked
    def cmd_vel(self, robot_id: str, linear_x: float, angular_z: float) -> dict:
        robot_id = self._resolve_robot_id(robot_id)

        robot = fleet_manager.get_robot(robot_id)

        if robot is None:
            raise ValueError(f"Robot을 찾을 수 없습니다: {robot_id}")

        if robot.state == RobotState.EMERGENCY_STOP:
            raise ValueError(f"비상정지 상태입니다: {robot_id}")

        if not robot.connected:
            raise ValueError(f"Robot이 연결되어 있지 않습니다: {robot_id}")

        if not math.isfinite(linear_x) or not math.isfinite(angular_z):
            raise ValueError("속도 명령은 유한한 값이어야 합니다.")
        active = (robot_id in self._navigation._executing
                  or robot_id in self._navigation._stopping
                  or robot_id in self._navigation._arrivals
                  or robot.state in (RobotState.DOCKING, RobotState.TASK_ASSIGNED)
                  or (robot.order_id is not None and robot.state == RobotState.WAITING))
        if active and (linear_x != 0.0 or angular_z != 0.0):
            raise ValueError(f"자동 동작 중입니다. 먼저 정지해야 합니다: {robot_id}")
        can_update = not active
        if robot_id in self._navigation._robots:
            can_update = self._navigation._traffic.validate_manual_velocity(
                robot_id, linear_x, angular_z) and can_update
        self._ros_node.publish_cmd_vel(robot_id=robot_id, linear_x=linear_x, angular_z=angular_z)

        if not can_update:
            pass
        elif linear_x == 0.0 and angular_z == 0.0:
            robot.set_state(RobotState.IDLE)
        else:
            robot.set_state(RobotState.MOVING)

        return {
            "type": "cmd_vel_ack",
            "robot_id": robot_id,
            "linear_x": linear_x,
            "angular_z": angular_z,
            "source": "ros2",
        }

    @_navigation_locked
    def emergency_stop(self, robot_id: str) -> dict:
        robot_id = self._resolve_robot_id(robot_id)
        robot = fleet_manager.get_robot(robot_id)

        if robot is None:
            raise ValueError(f"Robot을 찾을 수 없습니다: {robot_id}")

        if not robot.connected:
            raise ValueError(f"Robot이 연결되어 있지 않습니다: {robot_id}")

        # 취소/전송 중 예외가 나도 비상정지 상태를 잃지 않는다.
        robot.set_state(RobotState.EMERGENCY_STOP)
        if robot_id in self._waiting_omx:
            job_id, _, _ = self._waiting_omx[robot_id]
            self._waiting_omx[robot_id] = (job_id, None, "emergency_stop")
        if robot.order_id is not None:
            job_id = robot.order_id
            self._waiting_omx[robot_id] = (job_id, None, "emergency_stop")
            if mqtt_manager.cancel_job(
                    job_id, callback=lambda rid=robot_id, job=job_id: self._on_omx_terminal(rid, job)):
                self._waiting_omx.pop(robot_id, None)
            robot.clear_order()
        self._ros_node.cancel_auxiliary(robot_id)
        # 실행 중인 Nav2 주행 취소
        self._navigation.stop(
            robot_id, callback=lambda: self._navigation.cancel_after_stop(robot_id),
            reason="emergency_stop")
        # 속도 명령 0
        self._ros_node.publish_cmd_vel(robot_id=robot_id, linear_x=0.0, angular_z=0.0)

        robot.route = None
        robot.goal_node = None
        robot.navigation_type = None
        robot.set_state(RobotState.EMERGENCY_STOP)
        confirmed = (robot_id not in self._navigation._stopping
                     and not self._ros_node.has_active_auxiliary(robot_id)
                     and robot_id not in self._waiting_omx)
        print(f"[{strftime('%H:%M:%S')}] [ROS GATEWAY STOP] robot={robot_id} "
              f"cancel_confirmed={confirmed}", flush=True)

        return {
            "success": True,
            "robot_id": robot_id,
            "command": "emergency-stop",
            "cancel_confirmed": confirmed,
            "source": "ros2",
        }

    def emergency_stop_all(self) -> dict:
        robots = fleet_manager.get_all_robots()

        stopped_robots = []
        confirmations = {}
        skipped_offline = []

        for robot in robots:
            if not robot.connected:
                skipped_offline.append(robot.robot_id)
                continue

            result = self.emergency_stop(robot.robot_id)
            stopped_robots.append(robot.robot_id)
            confirmations[robot.robot_id] = result["cancel_confirmed"]

        return {
            "success": True,
            "command": "emergency-stop-all",
            "robots": stopped_robots,
            "cancel_confirmed": confirmations,
            "skipped_offline": skipped_offline,
            "source": "ros2",
        }

    @_navigation_locked
    def emergency_release(self, robot_id: str) -> dict:
        robot_id = self._resolve_robot_id(robot_id)
        robot = fleet_manager.get_robot(robot_id)

        if robot is None:
            raise ValueError(f"Robot을 찾을 수 없습니다: {robot_id}")

        if not robot.connected:
            raise ValueError(f"Robot이 연결되어 있지 않습니다: {robot_id}")

        if robot.state != RobotState.EMERGENCY_STOP:
            raise ValueError(f"비상정지 상태가 아닙니다: {robot_id}")

        if robot_id in self._navigation._stopping:
            raise ValueError(f"주행 취소 종료를 기다리고 있습니다: {robot_id}")
        if self._ros_node.has_active_auxiliary(robot_id):
            raise ValueError(f"도킹 또는 ArUco Action 종료를 기다리고 있습니다: {robot_id}")
        if robot_id in self._waiting_omx:
            raise ValueError(f"OMX 작업 종료를 기다리고 있습니다: {robot_id}")
        robot.set_state(RobotState.IDLE)

        return {
            "success": True,
            "robot_id": robot_id,
            "command": "emergency-release",
            "state": RobotState.IDLE.value,
            "source": "ros2",
        }

    def emergency_release_all(self) -> dict:
        robots = fleet_manager.get_all_robots()

        released_robots = []

        for robot in robots:
            if not robot.connected:
                continue

            if robot.state != RobotState.EMERGENCY_STOP:
                continue

            self.emergency_release(robot.robot_id)
            released_robots.append(robot.robot_id)

        return {
            "success": True,
            "command": "emergency-release-all",
            "robots": released_robots,
            "source": "ros2",
        }

    @_navigation_locked
    def llm_start_node(self, robot_id: str) -> str:
        """Allow a new LLM route only after confirmed completion at a node."""
        robot_id = normalize_robot_id(robot_id)
        robot = fleet_manager.get_robot(robot_id)
        if robot is None or not robot.connected:
            raise ValueError("실제 로봇이 연결되어 있지 않습니다.")
        if (robot.state != RobotState.IDLE
                or robot.route is not None
                or self._navigation.has_active_request(robot_id)
                or robot_id in self._waiting_omx
                or (self._ros_node is not None
                    and self._ros_node.has_active_auxiliary(robot_id))):
            raise ValueError("로봇이 주행 중이거나 대기 중입니다. 정지 후 다시 시도하세요.")
        if robot.occupied_node is None:
            raise ValueError("현재 로봇이 노드 위에 있지 않아 경로를 계산할 수 없습니다.")
        return str(robot.occupied_node)

    # 실제 로봇을 Route Graph의 목적지 Node로 이동
    @_navigation_locked
    def navigate_to_node(
        self, robot_id: str, node_id: str | int, *,
        _order_step=False, required_path: list[str] | None = None,
    ) -> dict:
        # Robot ID 정규화 및 ROS 등록 여부 확인
        robot_id = self._resolve_robot_id(robot_id)
        robot = fleet_manager.get_robot(robot_id)

        if robot is None:
            raise ValueError(f"Robot을 찾을 수 없습니다: {robot_id}")

        if robot.state == RobotState.EMERGENCY_STOP:
            raise ValueError(f"비상정지 상태입니다: {robot_id}")

        self._validate_navigation_request(robot_id, node_id)
        if required_path is not None:
            if _order_step:
                # Order legs start while TASK_ASSIGNED/WAITING, not IDLE.
                # Still require the robot to occupy the path's first node.
                if robot.order_id is None or robot.occupied_node is None:
                    raise ValueError("주문 경로를 시작할 현재 노드를 확인할 수 없습니다.")
                if robot.route is not None or robot.state not in (
                    RobotState.TASK_ASSIGNED, RobotState.WAITING,
                ):
                    raise ValueError("이전 주문 이동이 완료되지 않았습니다.")
                start_node = str(robot.occupied_node)
            else:
                start_node = self.llm_start_node(robot_id)
            if (not required_path or str(required_path[-1]) != str(node_id)
                    or str(required_path[0]) != start_node):
                raise ValueError("LLM 경로의 현재 노드 또는 목적지가 일치하지 않습니다.")
            find_edge_ids(load_route_graph(), [str(node) for node in required_path])
        same_active_goal = (
            robot.goal_node == str(node_id)
            and (_order_step or robot.order_id is None)
            and robot.state in (RobotState.MOVING, RobotState.WAITING)
            and robot_id not in self._navigation._stopping
            and (robot_id in self._navigation._requests
                 or robot_id in self._navigation._executing)
        )
        if not same_active_goal:
            self._stop_before_navigation(
                robot_id, lambda: self._start_navigation(
                    robot_id, node_id, required_path=required_path
                ),
                "new_goal_request", cancel_order=not _order_step)

        return {
            "success": True,
            "status": "PROCESSING",
            "robot_id": robot_id,
            "command": "goal-node",
            "target_node": str(node_id),
            "source": "ros2",
        }

    @_navigation_locked
    def navigate_to_charging_station(self, robot_id: str) -> dict:
        robot_id = self._resolve_robot_id(robot_id)
        robot = fleet_manager.get_robot(robot_id)

        if robot is None:
            raise ValueError(f"Robot을 찾을 수 없습니다: {robot_id}")

        if robot.state == RobotState.EMERGENCY_STOP:
            raise ValueError(f"비상정지 상태입니다: {robot_id}")

        charging_node = CHARGING_STATION_NODES.get(robot_id)

        if charging_node is None:
            raise ValueError(f"충전 스테이션이 지정되지 않은 Robot입니다: {robot_id}")

        self._validate_navigation_request(robot_id, charging_node)
        self._stop_before_navigation(
            robot_id,
            lambda: self._start_navigation(robot_id, charging_node, NavigationType.CHARGING),
            "charging_request")

        return {
            "success": True,
            "status": "PROCESSING",
            "robot_id": robot_id,
            "command": "charging",
            "target_node": charging_node,
            "source": "ros2",
        }

    @_navigation_locked
    def _start_navigation(
        self,
        robot_id: str,
        node_id: str | int,
        navigation_type: NavigationType = NavigationType.GOAL,
        *,
        required_path: list[str] | None = None,
    ) -> None:
        # 경로/예약 정책은 시뮬레이션과 동일한 TrafficManager를 사용한다.
        # 기존 이동 목적과 최종 도착 이후의 시퀀스는 Robot에 유지한다.
        try:
            self._navigation.request(
                robot_id, node_id, navigation_type, required_path=required_path
            )
        except (ValueError, RuntimeError):
            robot = fleet_manager.get_robot(robot_id)
            if robot is not None:
                self._navigation._pause(robot_id, "navigation_request_failed")
            raise

    @_navigation_locked
    def on_navigation_result(self, robot_id: str, status: int) -> None:
        robot = fleet_manager.get_robot(robot_id)

        if robot is None:
            return

        if status == GoalStatus.STATUS_SUCCEEDED:
            if robot.state in (RobotState.EMERGENCY_STOP, RobotState.PAUSED) or not robot.connected:
                return
            # 최종 후속 작업도 같은 원본 좌표/최신성/거리 조건을 통과해야 한다.
            try:
                if robot.goal_node is None:
                    raise ValueError("최종 목적지가 없습니다.")
                goal = get_node(robot.goal_node)
                distance = measured_distance(robot, (goal["x"], goal["y"]), monotonic())
                print(f"[{strftime('%H:%M:%S')}] [ROS GATEWAY ARRIVAL] robot={robot_id} "
                      f"goal={robot.goal_node} distance={distance:.3f}m "
                      f"tolerance={ARRIVAL_DISTANCE_THRESHOLD:.3f}m", flush=True)
                if distance > ARRIVAL_DISTANCE_THRESHOLD:
                    raise ValueError(f"도착 위치 불일치: {distance:.3f}m")
            except (OSError, KeyError, ValueError) as exc:
                self._navigation._pause(robot_id, f"final_arrival_failed:{exc}")
                return

            # 가장 가까운 노드 복귀 완료
            if robot.navigation_type == NavigationType.RETURN:
                robot.current_node = robot.goal_node
                robot.navigation_type = None
                robot.route = None
                robot.set_state(RobotState.IDLE)
                print(f"[{strftime('%H:%M:%S')}] [ROS GATEWAY RETURN] robot={robot_id} "
                      f"node={robot.current_node}", flush=True)
                return

            if robot.navigation_type == NavigationType.CHARGING:
                print(f"[{strftime('%H:%M:%S')}] [ROS GATEWAY CHARGING] robot={robot_id} "
                      f"station={robot.goal_node}", flush=True)

                robot.set_state(RobotState.DOCKING)
                try:
                    self._ros_node.send_precision_dock(robot_id)
                except (ValueError, RuntimeError) as exc:
                    robot.set_state(RobotState.PAUSED)
                    print(f"[{strftime('%H:%M:%S')}] [ROS GATEWAY DOCK ERROR] "
                          f"robot={robot_id} goal_send_failed={exc!r}", flush=True)
                return

            # 일반 목적지 이동 완료
            print(f"[{strftime('%H:%M:%S')}] [ROS GATEWAY ARRIVAL] robot={robot_id} "
                  f"goal={robot.goal_node}", flush=True)

            robot.current_node = robot.goal_node
            robot.navigation_type = None
            robot.route = None

            # 현재 목적지 Node의 ArUco Marker ID 확인
            marker_id = ARUCO_MARKER_IDS.get(robot.current_node)

            if marker_id is not None:
                robot.set_state(RobotState.DOCKING)

                print(f"[{strftime('%H:%M:%S')}] [ROS GATEWAY ARUCO] robot={robot_id} "
                      f"node={robot.current_node} alignment starting marker_id={marker_id}",
                      flush=True)

                try:
                    self._ros_node.send_aruco_align(robot_id=robot_id, marker_id=marker_id)
                except (ValueError, RuntimeError) as exc:
                    robot.set_state(RobotState.PAUSED)
                    print(f"[{strftime('%H:%M:%S')}] [ROS GATEWAY ARUCO ERROR] "
                          f"robot={robot_id} goal_send_failed={exc!r}", flush=True)
                return

            # ArUco 정렬 대상이 아닌 일반 Node
            robot.set_state(RobotState.IDLE)

        elif status == GoalStatus.STATUS_CANCELED:
            # 취소 처리
            robot.route = None
            pass

        elif status == GoalStatus.STATUS_ABORTED:
            # 실패 처리
            robot.set_state(RobotState.PAUSED)

    @_navigation_locked
    def return_to_nearest_node(self, robot_id: str) -> dict:
        robot_id = self._resolve_robot_id(robot_id)

        robot = fleet_manager.get_robot(robot_id)

        if robot is None:
            raise ValueError(f"Robot을 찾을 수 없습니다: {robot_id}")

        if not robot.connected:
            raise ValueError(f"Robot이 연결되어 있지 않습니다: {robot_id}")

        if robot.state == RobotState.EMERGENCY_STOP:
            raise ValueError(f"비상정지 상태입니다: {robot_id}")

        if robot.x is None or robot.y is None:
            raise ValueError(f"Robot 위치를 아직 받지 못했습니다: {robot_id}")

        graph = load_route_graph()
        path_plan = DistanceAStar(graph)

        nearest_node = find_nearest_node(nodes=path_plan.nodes, x=robot.x, y=robot.y)

        if nearest_node is None:
            raise ValueError("가장 가까운 Node를 찾을 수 없습니다.")

        target = get_node(nearest_node)

        # 기존 복귀 목적과 yaw는 유지하며 동일한 예약 실행부를 통과한다.
        self._validate_navigation_request(robot_id, nearest_node)
        self._stop_before_navigation(
            robot_id,
            lambda: self._start_navigation(robot_id, nearest_node, NavigationType.RETURN),
            "return_request")

        return {
            "success": True,
            "status": "SUCCESS",
            "robot_id": robot_id,
            "command": "return-nearest-node",
            "nearest_node": nearest_node,
            "target": {
                "node_id": target["id"],
                "x": target["x"],
                "y": target["y"],
            },
            "source": "ros2",
        }

    @_navigation_locked
    def on_precision_dock_result(self, robot_id: str, status: int) -> None:
        robot = fleet_manager.get_robot(robot_id)

        if robot is None:
            return

        if not robot.connected or robot.state != RobotState.DOCKING:
            return

        if status == GoalStatus.STATUS_SUCCEEDED:
            robot.current_node = robot.goal_node
            robot.set_state(RobotState.IDLE)
            robot.navigation_type = None
            robot.route = None
            print(f"[{strftime('%H:%M:%S')}] [ROS GATEWAY DOCK] robot={robot_id} completed", flush=True)
        else:
            robot.set_state(RobotState.PAUSED)
            print(f"[{strftime('%H:%M:%S')}] [ROS GATEWAY DOCK] robot={robot_id} failed", flush=True)

    @_navigation_locked
    def on_aruco_align_result(self, robot_id: str, status: int) -> None:
        robot = fleet_manager.get_robot(robot_id)

        if robot is None:
            return

        if not robot.connected or robot.state != RobotState.DOCKING:
            return

        if status == GoalStatus.STATUS_SUCCEEDED:
            print(f"[{strftime('%H:%M:%S')}] [ROS GATEWAY ARUCO] robot={robot_id} "
                  f"aligned node={robot.current_node}", flush=True)

            if robot.order_id is None:
                # 일반 Node 이동은 정렬만 완료한다. 주문 없는 OMX 명령은 보내지 않는다.
                robot.set_state(RobotState.IDLE)
                print(f"[{strftime('%H:%M:%S')}] [ROS GATEWAY ARUCO] robot={robot_id} "
                      "no order, OMX skipped", flush=True)
                return

            # 현재 Node에 연결된 OMX 조회
            omx_id = NODE_OMX_MAP.get(robot.current_node)

            if omx_id is None:
                print(f"[{strftime('%H:%M:%S')}] [ROS GATEWAY ARUCO] robot={robot_id} "
                      f"no OMX for node={robot.current_node}", flush=True)
                robot.set_state(RobotState.IDLE)
                return

            # 현재 Node에서 처리할 품목 조회
            item_keys = NODE_ITEM_MAP.get(robot.current_node, [])
            items = {}

            for key in item_keys:
                quantity = robot.order_items.get(key, 0)
                if quantity > 0:
                    items[key] = quantity

            if not items:
                robot.set_state(RobotState.PAUSED)
                print(f"[{strftime('%H:%M:%S')}] [ROS GATEWAY ARUCO] robot={robot_id} "
                      f"order={robot.order_id} has no items for node={robot.current_node}", flush=True)
                return

            print(f"[{strftime('%H:%M:%S')}] [ROS GATEWAY MQTT] robot={robot_id} "
                  f"omx={omx_id} items={items}", flush=True)

            # 빠른 MQTT Result가 publish 직후 도착해도 현재 단계의 결과로 처리한다.
            robot.set_state(RobotState.WAITING)
            try:
                mqtt_manager.send_job(omx_id=omx_id, job_id=robot.order_id, items=items)
            except (ValueError, RuntimeError) as e:
                print(f"[{strftime('%H:%M:%S')}] [ROS GATEWAY MQTT ERROR] "
                      f"robot={robot_id} error={e!r}", flush=True)
                robot.set_state(RobotState.PAUSED)
                return

        else:
            print(f"[{strftime('%H:%M:%S')}] [ROS GATEWAY ARUCO] robot={robot_id} "
                  f"failed status={status}", flush=True)
            robot.set_state(RobotState.PAUSED)


ros_gateway = RosGateway()
