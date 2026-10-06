

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from time import monotonic
from typing import Any

from ..schemas.robot import normalize_robot_id, to_ui_robot_id
from .map_service import world_to_pixel
from .route_graph import get_node, load_route_graph
from .pathfinding import DistanceAStar
from .reservation import reservation_tables
from .occupancy import locate_occupancy, occupied_resource
from .traffic_manager import TrafficManager

import math

SIMULATION_SPEED_MPS = 0.2
RESERVATION_MARGIN_S = 0.2

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


class MockFmsStore:
    """Volatile state used only to keep the frontend contract operational."""

    # MockFmsStore - FMS 상태를 유지하는 임시 저장소
    def __init__(self, reservations=None) -> None:
        self._robots: dict[str, dict[str, Any]] = {}
        self._traffic = TrafficManager(
            self._robots, reservations, speed_mps=SIMULATION_SPEED_MPS,
            safety_margin=RESERVATION_MARGIN_S,
        )
        self._lock = self._traffic.lock
        self._last_tick = monotonic()
        self._blocked_ips: set[str] = set()
        self.reset()

    def reset(self) -> None:
        with self._lock:
            self._traffic.reset_after_stop()
            self._last_tick = monotonic()
            self._robots.clear()
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
                    "occupied_node": str(node["id"]),
                    "occupied_edge": None,
                    "route": None,
                    "goal_node": None,
                    "navigation_id": None,
                    "request_order": None,
                    "stop_requested": False,
                    "map_pose_received": True,
                    "connection_state": "ONLINE",
                }

    def _get_robot(self, robot_id: str) -> dict[str, Any]:
        backend_id = normalize_robot_id(robot_id)
        robot = self._robots.get(backend_id)

        if robot is None:
            raise ValueError(f"Unknown robot: {backend_id}")
        return robot

    def advance_simulation(self, dt: float, now: float | None = None):
        """한 tick의 재예약·진입·이동을 같은 잠금과 시각으로 처리한다."""
        if not math.isfinite(dt) or dt <= 0:
            return
        now = monotonic() if now is None else now
        if not math.isfinite(now):
            return
        with self._lock:
            if now <= self._last_tick:
                return
            elapsed = min(dt, now - self._last_tick)
            self._last_tick = now
            if not self._traffic.has_active_requests():
                return
            graph = load_route_graph()
            planner = DistanceAStar(graph)
            self._traffic.retry_waiting(now, graph, planner)
            for robot_id in self._robots:
                self.advance_mock_robot(robot_id, elapsed, now=now, graph=graph, nodes=planner.nodes)
            self._traffic.retry_waiting(now, graph, planner)

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

    
    def navigate_to_node(self, robot_id: str, node_id: str | int) -> dict[str, Any]:
        """가상 로봇의 이동 요청을 공통 교통 제어 서비스에 전달한다."""
        with self._lock:
            robot = self._get_robot(robot_id)
            target = get_node(node_id)

            graph = load_route_graph()
            # 시뮬레이션은 이 잠금 안에서 즉시 정지할 수 있다.
            self._traffic.request_navigation_after_stop(
                robot["robot_id"], target["id"], now=monotonic(), graph=graph,
            )
            already_arrived = robot["goal_node"] is None
            response_route = deepcopy(robot["route"])  # 응답 경로는 잠금 안에서 복사하는 편이 좋음
            waiting = robot["status"] == "WAITING"

        result = self._command_response(
            robot_id,
            "goal-node",
            {"node_id": target["id"], "x": target["x"], "y": target["y"]},
        )

        if already_arrived:
            result["message"] = "이미 목적지 노드에 있습니다."
        elif waiting:
            result["status"] = "WAITING"
            result["message"] = "현재 위치에서 예약 또는 출발 시각을 기다립니다."

        result["route"] = response_route
        result["node"] = target
        return result

    # 로봇 목적지 좌표 이동 명령
    def navigate_to_pose(self, robot_id: str, x: float, y: float) -> dict[str, Any]:
        """테스트용 즉시 위치 변경. 실제 주행 명령이 아니다."""
        with self._lock:
            graph = load_route_graph()
            path_plan = DistanceAStar(graph)
            x, y = float(x), float(y)
            occupied_node, occupied_edge = locate_occupancy(
                graph, path_plan.nodes, x, y,
            )

            robot = self._get_robot(robot_id)
            probe = dict(robot, occupied_node=occupied_node, occupied_edge=occupied_edge)
            resource = occupied_resource(probe, graph)
            now = monotonic()
            if self._traffic.is_resource_blocked(robot["robot_id"], resource, now=now, graph=graph):
                raise ValueError("좌표 이동 위치가 다른 로봇에 의해 점유 또는 예약되어 있습니다.")
            self.stop_robot(robot_id)
            robot.update(
                {
                    "x": float(x),
                    "y": float(y),
                    # 좌표와 실제 점유를 함께 교체한다. 구간 사이에서는 current_node=None.
                    "current_node": occupied_node,
                    "occupied_node": occupied_node,
                    "occupied_edge": occupied_edge,
                    "status": "IDLE",
                    "route": None,
                    "stop_requested": False,
                }
            )

        return self._command_response(
            robot_id,
            "goal",
            {"target_x": float(x), "target_y": float(y)},
        )

    def stop_robot(self, robot_id: str) -> dict[str, Any]:
        """가상 로봇을 즉시 정지하고 요청을 취소한다."""
        with self._lock:
            robot = self._get_robot(robot_id)
            self._traffic.cancel_navigation_after_stop(robot["robot_id"])
        return self._command_response(robot_id, "stop", None)

    def cmd_vel(self, robot_id: str, linear_x: float, angular_z: float) -> dict[str, Any]:
        """공통 수동 조작 정책을 검사하고 mock 표시 상태를 갱신한다."""
        with self._lock:
            robot = self._get_robot(robot_id)
            can_update = self._traffic.validate_manual_velocity(robot["robot_id"], linear_x, angular_z)
            if can_update and robot["status"] != "NAVIGATING":
                robot["status"] = "MOVING" if linear_x or angular_z else "IDLE"
        return {
            "type": "ack",
            "data": self._command_response(
                robot_id,
                "cmd_vel",
                {"linear_x": float(linear_x), "angular_z": float(angular_z)},
            ),
        }

    def advance_mock_robot(self, robot_id: str, dt: float, speed_mps: float = SIMULATION_SPEED_MPS, *, now: float | None = None, graph=None, nodes=None) -> None:
        # 방어 코드
        if not math.isfinite(dt) or not math.isfinite(speed_mps):
            return
        if dt <= 0.0 or speed_mps <= 0.0:
            return
        if speed_mps != SIMULATION_SPEED_MPS:
            raise ValueError("이동 속도는 예약 계산에 사용한 시뮬레이션 속도와 같아야 합니다.")

        now = monotonic() if now is None else now
        if not math.isfinite(now):
            return
        with self._lock:
            robot = self._get_robot(robot_id)
            route = robot["route"]

            if route is None or route.get("departure_at") is None:
                return
            dt = min(dt, max(0.0, now - route["departure_at"]))
            if dt <= 0:
                return
            if graph is None:
                graph = load_route_graph()
            if nodes is None:
                nodes = DistanceAStar(graph).nodes
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

                target_id = node_ids[next_index]
                target_x, target_y = nodes[target_id]
                dx = target_x - robot["x"]
                dy = target_y - robot["y"]
                distance = math.hypot(dx, dy)

                departure = route["segment_departures"][route["segment_index"]]
                remaining = min(remaining, speed_mps * max(0.0, now - departure))
                finish = now + (distance - remaining) / speed_mps
                permission = self._traffic.check_segment_permission(
                    robot["robot_id"], now=now, expected_arrival_at=finish, graph=graph,
                )
                if permission.decision == "replan":
                    # mock 실행은 즉시 정지한다. 실제 실행기는 정지 확인 후 호출해야 한다.
                    self._traffic.wait_for_reservation_after_stop(robot["robot_id"])
                    return
                if permission.decision == "waiting":
                    robot["status"] = "WAITING"
                    route["phase"] = "waiting"
                    return
                if remaining <= 0:
                    return
                robot["status"] = "NAVIGATING"
                route["phase"] = "moving"

                if distance > 0.0:
                    # 되돌아가는 경로도 이동 방향으로 회전한 전진이고
                    # 차체 방향을 유지하는 실제 후진 명령으로 취급하지 않음
                    robot["yaw"] = route["waypoint_yaws"][next_index]

                # 다음 노드까지 도착하고 남은 거리로 계속 진행
                if distance <= remaining:
                    robot["x"] = target_x
                    robot["y"] = target_y
                    self._traffic.confirm_node_arrival(robot["robot_id"], target_id)
                    remaining -= distance
                    if robot["route"] is None:
                        return

                else:
                    # 목표 노드 방향으로 remaining만큼 이동
                    ratio = remaining / distance
                    robot["x"] += dx * ratio
                    robot["y"] += dy * ratio

                    # 노드 사이를 이동하는 상태
                    self._traffic.confirm_edge_occupancy(robot["robot_id"])
                    return


mock_fms = MockFmsStore(reservation_tables["simulation"])
