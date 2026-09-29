from __future__ import annotations

from typing import Any
from copy import deepcopy

from ..models.robot import RobotState

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

GOAL_YAWS = {
    "0": 0.0,
    "1": 0.0,
    "2": 0.0,
    "3": 0.0,
    "4": 0.0,
    "5": -math.pi / 2,
    "6": -math.pi / 2,
}


class RosGateway:
    def __init__(self) -> None:
        self._ros_node: FmsRosNode | None = None

    def set_ros_node(self, ros_node: FmsRosNode) -> None:
        self._ros_node = ros_node
        ros_node.navigation_result_callback = self.on_navigation_result
        ros_node.spin_result_callback = self.on_spin_result
        ros_node.precision_dock_result_callback = self.on_precision_dock_result

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
    def cmd_vel(self, robot_id: str, linear_x: float, angular_z: float) -> dict:
        robot_id = self._resolve_robot_id(robot_id)

        robot = fleet_manager.get_robot(robot_id)

        if robot is None:
            raise ValueError(f"Robot을 찾을 수 없습니다: {robot_id}")

        if not robot.connected:
            raise ValueError(f"Robot이 연결되어 있지 않습니다: {robot_id}")

        self._ros_node.publish_cmd_vel(robot_id=robot_id, linear_x=linear_x, angular_z=angular_z)

        if linear_x == 0.0 and angular_z == 0.0:
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

    # 실제 로봇을 Route Graph의 목적지 Node로 이동
    def navigate_to_node(self, robot_id: str, node_id: str | int) -> dict:

        # Robot ID 정규화 및 ROS 등록 여부 확인
        robot_id = self._resolve_robot_id(robot_id)

        self._ros_node.cancel_follow_waypoints(
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

    def _start_navigation(self, robot_id: str, node_id: str | int) -> None:
        # FleetManager에서 실제 Robot 객체 조회
        robot = fleet_manager.get_robot(robot_id)

        if robot is None:
            raise ValueError(f"Robot을 찾을 수 없습니다: {robot_id}")

        # 재계획에 실패하더라도 취소된 경로를 활성 경로로 계속 전송하지 않도록 초기화. 기존 Goal 취소가 확인된 뒤 호출
        robot.route = None
        robot.goal_node = None
        robot.navigation_type = None

        # Zenoh 연결 상태 확인
        if not robot.connected:
            raise ValueError(f"Robot이 연결되어 있지 않습니다: {robot_id}")

        # AMCL 위치를 아직 받지 못한 경우 경로 생성 불가
        if robot.x is None or robot.y is None:
            raise ValueError(f"Robot 위치를 아직 받지 못했습니다: {robot_id}")

        # 목적지 Node 조회
        target = get_node(node_id)

        # Route Graph 로드
        graph = load_route_graph()

        # 기존 A* 경로 탐색기 생성
        path_plan = DistanceAStar(graph)

        # AMCL 위치를 기준으로 가까운 Node 판정
        current_node = find_nearest_node(nodes=path_plan.nodes, x=robot.x, y=robot.y)

        if current_node is None:
            raise ValueError("가장 가까운 Node를 찾을 수 없습니다.")

        # 현재 Node -> 목적지 Node 경로 생성
        path = path_plan.plan(start=current_node, end=target["id"], speed_mps=0.025)
        if path is None:
            raise ValueError("방향성 그래프에서 도달 가능한 경로가 없습니다.")

        # 경로에 포함된 Node / Edge ID
        node_ids = list(path.route)
        edge_ids = find_edge_ids(graph, node_ids)
        robot.current_node = current_node
        robot.goal_node = str(target["id"])
        robot.navigation_type = "goal"

        robot.route = {
            "node_ids": node_ids,
            "edge_ids": edge_ids,
            "phase": "ready",
            "segment_index": 0,
        }

        # 경로의 Node ID를 실제 Map 좌표로 변환

        waypoints = []

        # 시작 노드와 목적지 노드가 같은 경우
        if len(node_ids) == 1:
            current = get_node(node_ids[0])

            waypoints.append(
                (
                    current["x"],
                    current["y"],
                    float(robot.yaw),
                )
            )

        else:
            # 경로에 포함된 모든 Node를 Waypoint로 변환
            for index in range(len(node_ids)):
                current_id = node_ids[index]
                current = get_node(current_id)

                # 마지막 노드가 아니면 다음 노드 방향
                if index < len(node_ids) - 1:
                    next_id = node_ids[index + 1]
                    next_node = get_node(next_id)

                    dx = next_node["x"] - current["x"]
                    dy = next_node["y"] - current["y"]

                # 마지막 노드는 이전 노드 -> 마지막 노드 진입 방향
                else:
                    previous_id = node_ids[index - 1]
                    previous = get_node(previous_id)

                    dx = current["x"] - previous["x"]
                    dy = current["y"] - previous["y"]

                yaw = math.atan2(dy, dx)

                waypoints.append((current["x"], current["y"], yaw))

        # 이미 목적지 Node에 있는 경우
        if not waypoints:
            robot.route = None

            return {
                "success": True,
                "status": "SUCCESS",
                "robot_id": robot_id,
                "command": "goal-node",
                "target": {
                    "node_id": target["id"],
                    "x": target["x"],
                    "y": target["y"],
                },
                "start_node": current_node,
                "route": {
                    "node_ids": node_ids,
                    "edge_ids": edge_ids,
                },
                "message": "이미 목적지 Node에 있습니다.",
                "source": "ros2",
            }

        # Nav2 FollowWaypoints Action으로 경로 전송
        robot.set_state(RobotState.MOVING)
        self._ros_node.send_follow_waypoints_goal(robot_id=robot_id, waypoints=waypoints)

        return {
            "success": True,
            "status": "SUCCESS",
            "robot_id": robot_id,
            "command": "goal-node",
            "target": {
                "node_id": target["id"],
                "x": target["x"],
                "y": target["y"],
            },
            "start_node": current_node,
            "route": {
                "node_ids": node_ids,
                "edge_ids": edge_ids,
            },
            "source": "ros2",
        }

    def on_navigation_result(self, robot_id: str, status: int) -> None:
        robot = fleet_manager.get_robot(robot_id)

        if robot is None:
            return

        if status == GoalStatus.STATUS_SUCCEEDED:
            # 가장 가까운 노드 복귀 완료
            if robot.navigation_type == "return":
                robot.current_node = robot.goal_node
                robot.navigation_type = None
                robot.route = None
                robot.set_state(RobotState.IDLE)
                print(f"[{robot_id}] 가장 가까운 노드 복귀 완료: " f"{robot.current_node}")
                return

            # 일반 목적지 이동 완료
            print(f"[{robot_id}] 목적지 도착: {robot.goal_node}")

            target_yaw = GOAL_YAWS.get(str(robot.goal_node))

            if target_yaw is None:
                robot.current_node = robot.goal_node
                robot.navigation_type = None
                robot.route = None
                robot.set_state(RobotState.IDLE)
                return

            current_yaw = float(robot.yaw)

            spin_yaw = target_yaw - current_yaw
            spin_yaw = math.atan2(math.sin(spin_yaw), math.cos(spin_yaw))  # -pi ~ pi 범위로 정규화

            YAW_TOLERANCE = math.radians(5)
            if abs(spin_yaw) <= YAW_TOLERANCE:
                self.on_spin_result(robot_id, GoalStatus.STATUS_SUCCEEDED)
                return

            robot.set_state(RobotState.MOVING)
            self._ros_node.send_spin(robot_id, spin_yaw)

        elif status == GoalStatus.STATUS_CANCELED:
            # 취소 처리
            robot.route = None
            pass

        elif status == GoalStatus.STATUS_ABORTED:
            # 실패 처리
            robot.set_state(RobotState.PAUSED)

    def return_to_nearest_node(self, robot_id: str) -> dict:
        robot_id = self._resolve_robot_id(robot_id)

        robot = fleet_manager.get_robot(robot_id)

        if robot is None:
            raise ValueError(f"Robot을 찾을 수 없습니다: {robot_id}")

        if not robot.connected:
            raise ValueError(f"Robot이 연결되어 있지 않습니다: {robot_id}")

        if robot.x is None or robot.y is None:
            raise ValueError(f"Robot 위치를 아직 받지 못했습니다: {robot_id}")

        graph = load_route_graph()
        path_plan = DistanceAStar(graph)

        nearest_node = find_nearest_node(nodes=path_plan.nodes, x=robot.x, y=robot.y)

        if nearest_node is None:
            raise ValueError("가장 가까운 Node를 찾을 수 없습니다.")

        target = get_node(nearest_node)

        # 복귀 명령임을 표시
        robot.navigation_type = "return"
        robot.set_state(RobotState.MOVING)
        robot.goal_node = str(nearest_node)

        self._ros_node.send_follow_waypoints_goal(
            robot_id=robot_id, waypoints=[(target["x"], target["y"], float(robot.yaw))]
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

    def on_spin_result(self, robot_id: str, status: int) -> None:
        robot = fleet_manager.get_robot(robot_id)

        if robot is None:
            return

        if status != GoalStatus.STATUS_SUCCEEDED:
            robot.set_state(RobotState.PAUSED)
            print(f"[{robot_id}] Spin 실패")
            return

        # 0, 1, 2번 노드에서만 정밀 도킹
        if str(robot.goal_node) in ["0", "1", "2"]:
            print(f"[{robot_id}] PrecisionDock 시작: {robot.goal_node}")
            robot.set_state(RobotState.DOCKING)
            self._ros_node.send_precision_dock(robot_id)
            return

        robot.current_node = robot.goal_node
        robot.navigation_type = None
        robot.route = None
        robot.set_state(RobotState.IDLE)


ros_gateway = RosGateway()
