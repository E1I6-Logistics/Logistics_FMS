from __future__ import annotations

from typing import Any
from copy import deepcopy

from ..schemas.robot import normalize_robot_id, to_ui_robot_id
from ..services.fleet_manager import fleet_manager
from ..services.route_graph import get_node, load_route_graph, find_edge_ids, locate_current_node
from ..services.pathfinding import DistanceAStar
from action_msgs.msg import GoalStatus


import math

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .fms_ros_node import FmsRosNode


class RosGateway:
    def __init__(self) -> None:
        self._ros_node: FmsRosNode | None = None

    def set_ros_node(self, ros_node: FmsRosNode) -> None:
        self._ros_node = ros_node
        ros_node.navigation_result_callback = self.on_navigation_result

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

        self._ros_node.publish_cmd_vel(robot_id=robot_id, linear_x=linear_x, angular_z=angular_z)

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

        # FleetManager에서 실제 Robot 객체 조회
        robot = fleet_manager.get_robot(robot_id)

        if robot is None:
            raise ValueError(f"Robot을 찾을 수 없습니다: {robot_id}")

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

        # AMCL 위치를 기준으로 현재 Node 판정
        current_node = locate_current_node(
            nodes=path_plan.nodes,
            x=robot.x,
            y=robot.y,
            tolerance_m=0.2,
        )

        if current_node is None:
            raise ValueError("Robot의 현재 Node를 알 수 없습니다.")

        # 현재 Node -> 목적지 Node 경로 생성
        path = path_plan.plan(start=current_node, end=target["id"], speed_mps=0.025)
        if path is None:
            raise ValueError("방향성 그래프에서 도달 가능한 경로가 없습니다.")

        # 경로에 포함된 Node / Edge ID
        node_ids = list(path.route)
        edge_ids = find_edge_ids(graph, node_ids)

        robot.route = {
            "node_ids": node_ids,
            "edge_ids": edge_ids,
            "phase": "ready",
            "segment_index": 0,
        }

        # 경로의 Node ID를 실제 Map 좌표로 변환
        waypoints = []

        # 첫 구간이 동일 좌표이면 현재 로봇 방향 유지
        previous_yaw = float(robot.yaw) if robot.yaw is not None else 0.0

        # 각 waypoint에 도착했을 때 해당 지점으로 진입한 구간의 방향을 계산하여 포함
        for previous_id, current_id in zip(node_ids, node_ids[1:]):
            previous = get_node(previous_id)
            current = get_node(current_id)

            dx = current["x"] - previous["x"]
            dy = current["y"] - previous["y"]
            # 동일 좌표 또는 매우 짧은 구간에서는 직전 방향 유지
            if math.hypot(dx, dy) > 1e-9:
                yaw = math.atan2(dy, dx)
            else:
                yaw = previous_yaw

            waypoints.append((current["x"], current["y"], yaw))
            previous_yaw = yaw

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

        if status == GoalStatus.STATUS_SUCCEEDED:
            # 도착 후 처리
            pass

        elif status == GoalStatus.STATUS_CANCELED:
            # 취소 처리
            pass

        elif status == GoalStatus.STATUS_ABORTED:
            # 실패 처리
            pass


ros_gateway = RosGateway()
