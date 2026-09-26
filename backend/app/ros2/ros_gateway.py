from __future__ import annotations
import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .fms_ros_node import FmsRosNode


class RosGateway:

    def __init__(self) -> None:

        self._ros_node: FmsRosNode | None = None

    def set_ros_node(self, ros_node: FmsRosNode) -> None:
        self._ros_node = ros_node

    def sync_connected_robots(self, connections: list[dict]) -> None:

        if self._ros_node is None:
            raise RuntimeError("FMS ROS node is not initialized")

        for connection in connections:
            if not connection.get("connected"):
                continue

            robot_id = str(connection.get("name", "")).strip()
            if not robot_id:
                continue

            self._ros_node.register_robot(robot_id)

    def _normalize_robot_id(self, robot_id: str) -> str:
        robot_id = robot_id.strip()

        # ROS/FMS 형식이면 그대로 사용
        if re.fullmatch(r"robot\d+", robot_id):
            return robot_id

        # UI 형식: R-01 -> robot1
        match = re.fullmatch(r"R-(\d+)", robot_id, re.IGNORECASE)

        if match:
            return f"robot{int(match.group(1))}"

        raise ValueError(f"Invalid robot ID: {robot_id}")

    def _resolve_robot_id(self, robot_id: str) -> str:
        robot_id = self._normalize_robot_id(robot_id)

        if self._ros_node is None:
            raise RuntimeError("ROS node is not initialized")

        if not self._ros_node.is_registered(robot_id):
            raise ValueError(f"Robot is not registered: {robot_id}")

        return robot_id

    def cmd_vel(self, robot_id: str, linear_x: float, angular_z: float) -> dict:
        robot_id = self._normalize_robot_id(robot_id)

        if self._ros_node is None:
            print("FMS ROS node is not initialized")
            raise RuntimeError("FMS ROS node is not initialized")

        # 해당 로봇이 아직 ROS Interface에 등록되지 않았다면
        # 연결된 로봇인지 확인 후 register 하는 구조는 다음 단계에서 연결
        if not self._ros_node.is_registered(robot_id):
            print(f"Robot is not registered: {robot_id}")
            raise ValueError(f"Robot is not registered: {robot_id}")
        self._ros_node.publish_cmd_vel(robot_id=robot_id, linear_x=linear_x, angular_z=angular_z)

        return {
            "type": "cmd_vel_ack",
            "robot_id": robot_id,
            "linear_x": linear_x,
            "angular_z": angular_z,
            "source": "ros2",
        }


ros_gateway = RosGateway()
