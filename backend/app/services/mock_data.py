"""Deterministic, in-memory frontend contract data.

No database, path planning, robot communication, or equipment control belongs
in this module. Replace each command TODO with project-specific control logic.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from threading import RLock
from typing import Any

from ..schemas.robot import normalize_robot_id, to_ui_robot_id
from .map_service import world_to_pixel
from .route_graph import get_node, load_route_graph, find_edge_ids
from .pathfinding import DistanceAStar

import math

_MOCK_ROBOT_DEFINITIONS = {
    "robot1": {"node_id": "0", "status": "IDLE", "battery": 92.0},
    "robot2": {"node_id": "1", "status": "IDLE", "battery": 78.0},
    "robot3": {"node_id": "2", "status": "IDLE", "battery": 64.0},
}

_MOCK_CONNECTIONS = {
    "10.10.141.225": "robot1",
    "10.10.141.221": "robot2",
    "10.10.141.222": "robot3",
}

# current_node 를 새로 식별하기 위해 가장 가까운 노드를 찾아 현재 노드 결정
# tolerance_m 은 "이 거리 안에 있으면 노드에 도착했다고 볼 것인가" -> 값은 지도 간격과 위치 측정 정확도에 맞춰 정해야 함
def locate_current_node(nodes, x, y, tolerance_m):
    if not nodes or not all(math.isfinite(v) for v in (x, y)):
        return None

    nearest_id = min(
        nodes,
        key=lambda node_id: math.dist((x, y), nodes[node_id]),
    )
    distance = math.dist((x, y), nodes[nearest_id])

    return nearest_id if distance <= tolerance_m else None

class MockFmsStore:
    """Volatile state used only to keep the frontend contract operational."""

    # MockFmsStore - FMS 상태를 유지하는 임시 저장소
    def __init__(self) -> None:
        self._lock = RLock()
        self._robots: dict[str, dict[str, Any]] = {}
        self._blocked_ips: set[str] = set()
        self.reset()

    def reset(self) -> None:
        with self._lock:
            self._robots = {}
            self._blocked_ips.clear()
            for robot_id, definition in _MOCK_ROBOT_DEFINITIONS.items():
                node = get_node(definition["node_id"])
                self._robots[robot_id] = {
                    "robot_id": robot_id,
                    "ui_id": to_ui_robot_id(robot_id),
                    "status": definition["status"],
                    "battery": definition["battery"],
                    "x": node["x"],
                    "y": node["y"],
                    "yaw": 0.0,
                    "current_node": str(node["id"]),
                    "route": None,
                    "map_pose_received": True,
                    "connection_state": "ONLINE",
                }

    def _get_robot(self, robot_id: str) -> dict[str, Any]:
        backend_id = normalize_robot_id(robot_id)
        robot = self._robots.get(backend_id)

        if robot is None:
            raise ValueError(f"Unknown robot: {backend_id}")
        return robot

    # 프론트에 보낼 Robot 상태 Snapshot 생성 기능
    @staticmethod
    def _snapshot(robot: dict[str, Any], mode: str) -> dict[str, Any]:
        result = deepcopy(robot)
        pixel_x, pixel_y = world_to_pixel(result["x"], result["y"])
        result.update(
            {
                "updated_at": datetime.now(timezone.utc).isoformat(),
                "mode": mode,
                "source": "mock",
                "pixel_x": pixel_x,
                "pixel_y": pixel_y,
                "pose_source": "MOCK",
            }
        )
        return result

    # 전체 Robot 상태 반환 기능
    def robot_snapshots(self, mode: str) -> list[dict[str, Any]]:
        with self._lock:
            return [self._snapshot(robot, mode) for robot in self._robots.values()]

    # 한가지 Robot 상태 반환 기능
    def robot_snapshot(self, robot_id: str, mode: str) -> dict[str, Any]:
        with self._lock:
            return self._snapshot(self._get_robot(robot_id), mode)

    # 현재 연결 상태를 Mock으로 반환
    def connections(self) -> list[dict[str, Any]]:
        with self._lock:
            return [
                {
                    "ip": ip,
                    "name": robot_id,
                    "known": True,
                    "connected": ip not in self._blocked_ips,
                    "blocked": ip in self._blocked_ips,
                    "state": "BLOCKED" if ip in self._blocked_ips else "CONNECTED",
                }
                for ip, robot_id in sorted(_MOCK_CONNECTIONS.items())
            ]

    # 공통 리스폰 생성 기능
    @staticmethod
    def _command_response(
        robot_id: str, command: str, target: dict[str, Any] | None
    ) -> dict[str, Any]:
        backend_id = normalize_robot_id(robot_id)
        return {
            "success": True,
            "status": "SUCCESS",
            "robot_id": backend_id,
            "ui_id": to_ui_robot_id(backend_id),
            "command": command,
            "target": target,
            "message": "Mock command accepted",
            "mock": True,
        }

    # 노드 경로 - 기본으로 시작지점과 목적지점만 존재
    def navigate_to_node(self, robot_id: str, node_id: str | int) -> dict[str, Any]:
        """TODO: Replace with user-defined path planning and node movement."""
        target = get_node(node_id)

        with self._lock:
            robot = self._get_robot(robot_id)

            # 임시 정책: 이동 중 재계획 미지원
            if robot["status"] in {"NAVIGATING", "MOVING"}:
                raise ValueError("이동 중 목적지 변경은 아직 지원하지 않습니다.")

            graph = load_route_graph()
            path_plan = DistanceAStar(graph)

            robot["current_node"] = locate_current_node(
                nodes=path_plan.nodes,
                x=robot["x"],
                y=robot["y"],
                tolerance_m=0.2,  # 예시: 노드 중심에서 20cm 이내
            )

            start_node = robot.get("current_node")  # 로봇 현재 노드
            if start_node is None:
                raise ValueError("로봇의 현재 노드를 알 수 없습니다.")

            path = path_plan.plan(start=start_node, end=target["id"], speed_mps=0.025)
            if path is None:
                raise ValueError("방향성 그래프에서 도달 가능한 경로가 없습니다.")

            node_ids = list(path.route)
            edge_ids = find_edge_ids(graph, node_ids)

            already_arrived = len(node_ids) == 1

            if already_arrived:
                robot["status"] = "IDLE"
                robot["route"] = None
            else:
                robot["status"] = "NAVIGATING"
                robot["route"] = {
                    "node_ids": node_ids,
                    "edge_ids": edge_ids,
                    "phase": "ready",
                    "segment_index": 0,
                }
            response_route = deepcopy(robot["route"]) # 응답 경로는 잠금 안에서 복사하는 편이 좋음

        result = self._command_response(
            robot_id,
            "goal-node",
            {"node_id": target["id"], "x": target["x"], "y": target["y"]},
        )

        if already_arrived:
            result["message"] = "이미 목적지 노드에 있습니다."

        result["route"] = response_route
        result["node"] = target
        return result

    # 로봇 목적지 좌표 이동 명령
    def navigate_to_pose(self, robot_id: str, x: float, y: float) -> dict[str, Any]:
        """TODO: Replace with user-defined coordinate movement control."""
        with self._lock:
            path_plan = DistanceAStar(load_route_graph())

            robot = self._get_robot(robot_id)
            robot.update(
                {
                    "x": float(x),
                    "y": float(y),
                    # current_node: 로봇이 현재 위치한다고 확인된 노드. 노드 사이이거나 위치를 확정할 수 없다면 None.
                    # currnet_node 를 갱신하지 않으면 좌표 이동 이후 노드 이동을 요청하면, 예전 노드에서 출발하는 경로를 계산할 수 있기 때문에
                    # 현재 노드와 실제 좌표를 맞추기 위해 좌표 이동 시 현재 노드 비우기
                    "current_node": None,
                    "status": "IDLE",
                    "route": None,
                }
            )
            robot["current_node"] = locate_current_node(
                nodes=path_plan.nodes,
                x=robot["x"],
                y=robot["y"],
                tolerance_m=0.2,
            )

        return self._command_response(
            robot_id,
            "goal",
            {"target_x": float(x), "target_y": float(y)},
        )

    def stop_robot(self, robot_id: str) -> dict[str, Any]:
        """TODO: Replace with user-defined robot stop control."""
        with self._lock:
            robot = self._get_robot(robot_id)
            robot["status"] = "IDLE"
            robot["route"] = None
        return self._command_response(robot_id, "stop", None)

    def cmd_vel(self, robot_id: str, linear_x: float, angular_z: float) -> dict[str, Any]:
        """TODO: Replace with user-defined velocity command transport."""
        with self._lock:
            robot = self._get_robot(robot_id)
            robot["status"] = "MOVING" if linear_x or angular_z else "IDLE"
        return {
            "type": "ack",
            "data": self._command_response(
                robot_id,
                "cmd_vel",
                {"linear_x": float(linear_x), "angular_z": float(angular_z)},
            ),
        }

    def advance_mock_robot(self, robot_id: str, dt: float, speed_mps: float = 0.025) -> None:
        # 방어 코드
        if not math.isfinite(dt) or not math.isfinite(speed_mps):
            return
        if dt <= 0.0 or speed_mps <= 0.0:
            return

        with self._lock:
            robot = self._get_robot(robot_id)
            route = robot["route"]

            if robot["status"] != "NAVIGATING" or route is None:
                return

            # 이번 갱신에서 이동할 수 있는 거리(m)
            remaining = speed_mps * dt
            node_ids = route["node_ids"]

            # 한 번의 갱신에서 여러 짧은 구간을 통과할 수도 있음
            while remaining > 0.0:
                next_index = route["segment_index"] + 1

                if next_index >= len(node_ids):
                    robot["status"] = "IDLE"
                    robot["route"] = None
                    raise ValueError("경로 진행 인덱스가 올바르지 않습니다.")

                target = get_node(node_ids[next_index])
                dx = target["x"] - robot["x"]
                dy = target["y"] - robot["y"]
                distance = math.hypot(dx, dy)

                route["phase"] = "moving"

                if distance > 0.0:
                    robot["yaw"] = math.atan2(dy, dx)

                # 다음 노드까지 도착하고 남은 거리로 계속 진행
                if distance <= remaining:
                    robot["x"] = target["x"]
                    robot["y"] = target["y"]
                    robot["current_node"] = str(target["id"])
                    route["segment_index"] = next_index
                    remaining -= distance

                    if next_index == len(node_ids) - 1:
                        robot["status"] = "IDLE"
                        robot["route"] = None
                        return

                else:
                    # 목표 노드 방향으로 remaining만큼 이동
                    ratio = remaining / distance
                    robot["x"] += dx * ratio
                    robot["y"] += dy * ratio

                    # 노드 사이를 이동하는 상태
                    robot["current_node"] = None
                    return


mock_fms = MockFmsStore()
