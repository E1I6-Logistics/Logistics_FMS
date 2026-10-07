from __future__ import annotations

from typing import Any
from copy import deepcopy
from functools import wraps
from ..services.real_navigation import RealNavigation


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

ARRIVAL_DISTANCE_THRESHOLD = 0.15  # 15cm

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
        self._navigation = RealNavigation(
            fleet_manager,
            lambda **kwargs: self._ros_node.send_follow_waypoints_goal(**kwargs),
            lambda *args, **kwargs: self._ros_node.cancel_follow_waypoints(*args, **kwargs),
            lambda robot_id: self.on_navigation_result(robot_id, GoalStatus.STATUS_SUCCEEDED),
            GOAL_YAWS, ARRIVAL_DISTANCE_THRESHOLD,
        )

    def set_ros_node(self, ros_node: FmsRosNode) -> None:
        self._ros_node = ros_node
        ros_node.navigation_lock = self._navigation.lock
        ros_node.navigation_result_callback = self._on_segment_result
        ros_node.precision_dock_result_callback = self.on_precision_dock_result
        ros_node.aruco_align_result_callback = self.on_aruco_align_result

    def _on_segment_result(self, robot_id: str, status: int) -> None:
        self._navigation.on_result(robot_id, status == GoalStatus.STATUS_SUCCEEDED)

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

        can_update = True
        if robot_id in self._navigation._robots:
            can_update = self._navigation._traffic.validate_manual_velocity(
                robot_id, linear_x, angular_z)
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

        # 실행 중인 Nav2 주행 취소
        self._navigation.stop(
            robot_id, callback=lambda: self._navigation.cancel_after_stop(robot_id))
        # 속도 명령 0
        self._ros_node.publish_cmd_vel(robot_id=robot_id, linear_x=0.0, angular_z=0.0)

        robot.route = None
        robot.goal_node = None
        robot.navigation_type = None
        robot.set_state(RobotState.EMERGENCY_STOP)

        return {
            "success": True,
            "robot_id": robot_id,
            "command": "emergency-stop",
            "source": "ros2",
        }

    def emergency_stop_all(self) -> dict:
        robots = fleet_manager.get_all_robots()

        stopped_robots = []

        for robot in robots:
            if not robot.connected:
                continue

            self.emergency_stop(robot.robot_id)
            stopped_robots.append(robot.robot_id)

        return {
            "success": True,
            "command": "emergency-stop-all",
            "robots": stopped_robots,
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

    def navigation_active(self, robot_id):
        return self._navigation is not None and self._navigation.is_active(robot_id)

    # 실제 로봇을 Route Graph의 목적지 Node로 이동
    @_navigation_locked
    def navigate_to_node(self, robot_id: str, node_id: str | int) -> dict:
        # Robot ID 정규화 및 ROS 등록 여부 확인
        robot_id = self._resolve_robot_id(robot_id)
        robot = fleet_manager.get_robot(robot_id)

        if robot is None:
            raise ValueError(f"Robot을 찾을 수 없습니다: {robot_id}")

        if robot.state == RobotState.EMERGENCY_STOP:
            raise ValueError(f"비상정지 상태입니다: {robot_id}")

        self._navigation.stop(
            robot_id, callback=lambda: self._start_navigation(robot_id, node_id)
        )

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

        self._navigation.stop(
            robot_id,
            callback=lambda: self._start_navigation(
                robot_id, charging_node, NavigationType.CHARGING
            ),
        )

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
    ) -> None:
        # 경로/예약 정책은 시뮬레이션과 동일한 TrafficManager를 사용한다.
        # 기존 이동 목적과 최종 도착 이후의 시퀀스는 Robot에 유지한다.
        try:
            self._navigation.request(robot_id, node_id, navigation_type)
        except (ValueError, RuntimeError):
            robot = fleet_manager.get_robot(robot_id)
            if robot is not None and robot.state != RobotState.EMERGENCY_STOP:
                robot.set_state(RobotState.PAUSED)
            raise

    @_navigation_locked
    def on_navigation_result(self, robot_id: str, status: int) -> None:
        robot = fleet_manager.get_robot(robot_id)

        if robot is None:
            return

        if status == GoalStatus.STATUS_SUCCEEDED:
            # 실제 현재 위치와 목적지 위치 거리 확인
            if robot.goal_node is not None:
                if robot.x is None or robot.y is None:
                    print(f"[{robot_id}] 도착 확인 실패: 현재 위치 정보 없음")
                    robot.set_state(RobotState.PAUSED)
                    return

                goal = get_node(robot.goal_node)

                dx = goal["x"] - robot.x
                dy = goal["y"] - robot.y
                distance = math.sqrt(dx * dx + dy * dy)

                print(
                    f"[{robot_id}] 도착 거리 확인: "
                    f"goal={robot.goal_node}, "
                    f"distance={distance:.3f}m"
                )

                if distance > ARRIVAL_DISTANCE_THRESHOLD:
                    print(
                        f"[{robot_id}] 도착 위치 불일치: "
                        f"{distance:.3f}m > {ARRIVAL_DISTANCE_THRESHOLD:.3f}m"
                    )
                    robot.set_state(RobotState.PAUSED)
                    return

            # 가장 가까운 노드 복귀 완료
            if robot.navigation_type == NavigationType.RETURN:
                robot.current_node = robot.goal_node
                robot.navigation_type = None
                robot.route = None
                robot.set_state(RobotState.IDLE)
                print(f"[{robot_id}] 가장 가까운 노드 복귀 완료: " f"{robot.current_node}")
                return

            if robot.navigation_type == NavigationType.CHARGING:
                print(f"[{robot_id}] 충전 스테이션 도착: {robot.goal_node}")

                robot.set_state(RobotState.DOCKING)
                self._ros_node.send_precision_dock(robot_id)
                return

            # 일반 목적지 이동 완료
            print(f"[{robot_id}] 목적지 도착: {robot.goal_node}")

            robot.current_node = robot.goal_node
            robot.navigation_type = None
            robot.route = None

            # 현재 목적지 Node의 ArUco Marker ID 확인
            marker_id = ARUCO_MARKER_IDS.get(robot.current_node)

            if marker_id is not None:
                robot.set_state(RobotState.DOCKING)

                print(
                    f"[{robot_id}] Node {robot.current_node} 도착 "
                    f"→ ArUco 정렬 시작 "
                    f"(marker_id={marker_id})"
                )

                self._ros_node.send_aruco_align(robot_id=robot_id, marker_id=marker_id)
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
        self._navigation.stop(
            robot_id,
            callback=lambda: self._start_navigation(robot_id, nearest_node, NavigationType.RETURN),
        )

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

        if status == GoalStatus.STATUS_SUCCEEDED:
            robot.current_node = robot.goal_node
            robot.set_state(RobotState.IDLE)
            robot.navigation_type = None
            robot.route = None
            print(f"[{robot_id}] PrecisionDock 완료")
        else:
            robot.set_state(RobotState.PAUSED)
            print(f"[{robot_id}] PrecisionDock 실패")

    @_navigation_locked
    def on_aruco_align_result(self, robot_id: str, status: int) -> None:
        robot = fleet_manager.get_robot(robot_id)

        if robot is None or robot.state == RobotState.EMERGENCY_STOP:
            return

        if status == GoalStatus.STATUS_SUCCEEDED:
            print(f"[{robot_id}] ArUco 정렬 성공: " f"Node {robot.current_node}")

            # 주문 없는 일반 노드 이동은 정렬로 완료한다. 빈 OMX 작업을 보내지 않는다.
            if robot.order_id is None:
                robot.set_state(RobotState.IDLE)
                return

            # 현재 Node에 연결된 OMX 조회
            omx_id = NODE_OMX_MAP.get(robot.current_node)

            if omx_id is None:
                print(f"[{robot_id}] 연결된 OMX가 없습니다: " f"Node {robot.current_node}")
                robot.set_state(RobotState.IDLE)
                return

            # 현재 Node에서 처리할 품목 조회
            item_keys = NODE_ITEM_MAP.get(robot.current_node, [])
            items = {}

            for key in item_keys:
                quantity = robot.order_items.get(key, 0)
                if quantity > 0:
                    items[key] = quantity

            print(f"[{robot_id}] MQTT 작업 요청: " f"{omx_id}, items={items}")

            try:
                mqtt_manager.send_job(omx_id=omx_id, job_id=robot.order_id, items=items)
            except (ValueError, RuntimeError) as e:
                print(f"[{robot_id}] MQTT 작업 요청 실패: " f"{e}")
                robot.set_state(RobotState.PAUSED)
                return
            robot.set_state(RobotState.WAITING)

        else:
            print(f"[{robot_id}] ArUco 정렬 실패: " f"status={status}")
            robot.set_state(RobotState.PAUSED)


ros_gateway = RosGateway()
