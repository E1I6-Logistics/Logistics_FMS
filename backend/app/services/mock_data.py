"""Deterministic, in-memory frontend contract data.

No database, path planning, robot communication, or equipment control belongs
in this module. Replace each command TODO with project-specific control logic.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from time import monotonic
from uuid import uuid4
from threading import RLock
from typing import Any

from ..schemas.robot import normalize_robot_id, to_ui_robot_id
from .map_service import world_to_pixel
from .route_graph import get_node, load_route_graph, find_edge_ids, locate_current_node
from .pathfinding import DistanceAStar
from .reservation import (
    ReservationTable,
    build_schedule,
    node_key,
    edge_key,
    overlaps,
    reservation_tables,
)

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
        self._reservations = reservations if reservations is not None else ReservationTable()
        self._pending: dict[str, None] = {}
        self._last_tick = monotonic()
        self._lock = RLock()
        self._robots: dict[str, dict[str, Any]] = {}
        self._blocked_ips: set[str] = set()
        self.reset()

    def reset(self) -> None:
        with self._lock:
            requests = {(row.robot_id, row.navigation_id) for row in self._reservations.snapshot()}
            for robot_id, navigation_id in requests:
                self._reservations.release_request(robot_id, navigation_id)
            self._pending.clear()
            self._last_tick = monotonic()
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
                    "occupied_node": str(node["id"]),
                    "occupied_edge": None,
                    "route": None,
                    "goal_node": None,
                    "navigation_id": None,
                    "map_pose_received": True,
                    "connection_state": "ONLINE",
                }

    def _get_robot(self, robot_id: str) -> dict[str, Any]:
        backend_id = normalize_robot_id(robot_id)
        robot = self._robots.get(backend_id)

        if robot is None:
            raise ValueError(f"Unknown robot: {backend_id}")
        return robot

    @staticmethod
    def _locate_occupancy(graph, nodes, x: float, y: float):
        """좌표 이동 후 그래프 위 점유를 판정한다. 방향별 edge ID는 유지한다."""
        if not all(math.isfinite(value) for value in (x, y)):
            raise ValueError("좌표는 유한한 값이어야 합니다.")
        node = locate_current_node(nodes, x, y, tolerance_m=1e-6)
        if node is not None:
            return node, None

        matches = {}
        for feature in graph["features"]:
            props = feature.get("properties") or {}
            if "startid" not in props or "endid" not in props:
                continue
            start, end = str(props["startid"]), str(props["endid"])
            ax, ay = nodes[start]
            bx, by = nodes[end]
            dx, dy = bx - ax, by - ay
            length_squared = dx * dx + dy * dy
            if length_squared == 0:
                continue
            fraction = ((x - ax) * dx + (y - ay) * dy) / length_squared
            if not 0 < fraction < 1:
                continue
            if math.hypot(x - ax - fraction * dx, y - ay - fraction * dy) <= 1e-6:
                matches.setdefault(tuple(sorted((start, end))), str(props["id"]))

        if len(matches) != 1:
            raise ValueError("좌표의 점유 노드 또는 통로를 확정할 수 없습니다.")
        return None, next(iter(matches.values()))

    def _occupied_resource(self, robot, graph):
        if robot["occupied_node"] is not None:
            return node_key(robot["occupied_node"])
        for feature in graph["features"]:
            props = feature.get("properties") or {}
            if (
                str(props.get("id")) == robot["occupied_edge"]
                and "startid" in props
                and "endid" in props
            ):
                return edge_key(props["startid"], props["endid"])
        raise ValueError("실제 점유 위치를 확인할 수 없습니다.")

    def _release_schedule(self, robot):
        # 시뮬레이션은 동일 잠금 안에서 즉시 정지하며 위치·점유는 유지한다.
        requests = {
            row.navigation_id
            for row in self._reservations.snapshot()
            if row.robot_id == robot["robot_id"]
        }
        for navigation_id in requests:
            self._reservations.release_request(robot["robot_id"], navigation_id)

    def _wait_for_reservation(self, robot):
        robot["status"] = "WAITING"
        if robot["route"] is not None:
            robot["route"]["phase"] = "waiting"
            robot["route"]["departure_at"] = None
        self._release_schedule(robot)
        self._pending.setdefault(robot["robot_id"], None)

    def _try_schedule(self, robot, now, graph, nodes):
        route = robot["route"]
        index = route["segment_index"]
        departure = now
        others = [row for row in self._reservations.snapshot() if row.robot_id != robot["robot_id"]]
        # 출발 시각만 이동한다. 무기한 점유나 해결되지 않는 대기는 다음 tick에서 재검사.
        for _ in range(128):
            batch = tuple(
                replace(row, segment_index=row.segment_index + index)
                for row in build_schedule(
                    robot["robot_id"],
                    robot["navigation_id"],
                    route["node_ids"][index:],
                    nodes,
                    (robot["x"], robot["y"]),
                    robot["occupied_node"],
                    now=now,
                    departure_at=departure,
                    speed_mps=SIMULATION_SPEED_MPS,
                    safety_margin=RESERVATION_MARGIN_S,
                )
            )
            for other in self._robots.values():
                if other is robot:
                    continue
                # 예약된 출발 시각을 가진 로봇은 시간표로 검사한다.
                other_route = other["route"]
                scheduled = other_route is not None and other_route.get("departure_at") is not None
                if not scheduled:
                    occupied = self._occupied_resource(other, graph)
                    if any(row.resource == occupied for row in batch):
                        return False
            conflicts = [
                (candidate, row)
                for candidate in batch
                for row in others
                if candidate.resource == row.resource and overlaps(candidate, row)
            ]
            if not conflicts:
                if not self._reservations.replace_request(
                    robot["robot_id"], robot["navigation_id"], batch
                ):
                    return False
                route["departure_at"] = departure
                route["phase"] = "ready"
                robot["status"] = "WAITING" if departure > now else "NAVIGATING"
                return True
            shift = max(row.end - candidate.start for candidate, row in conflicts)
            if not math.isfinite(shift):
                return False
            # 대기 장소의 예약이 충돌하면 출발을 늦춰도 해결되지 않는다.
            occupied = self._occupied_resource(robot, graph)
            if any(
                candidate.resource == occupied and candidate.start <= now
                for candidate, row in conflicts
            ):
                return False
            departure += shift + 1e-6
        return False

    def _retry_waiting(self, now, graph, nodes):
        for robot_id in list(self._pending):
            robot = self._robots[robot_id]
            if robot["goal_node"] is None:
                self._pending.pop(robot_id, None)
            elif self._try_schedule(robot, now, graph, planner):
                self._pending.pop(robot_id, None)

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
            if not any(robot["goal_node"] is not None for robot in self._robots.values()):
                return
            graph = load_route_graph()
            planner = DistanceAStar(graph)
            self._retry_waiting(now, graph, planner)
            for robot_id in self._robots:
                self.advance_mock_robot(
                    robot_id, elapsed, now=now, graph=graph, nodes=planner.nodes
                )
            self._retry_waiting(now, graph, planner)

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
        with self._lock:
            robot = self._get_robot(robot_id)
            target = get_node(node_id)

            graph = load_route_graph()
            path_plan = DistanceAStar(graph)
            current_node = robot["occupied_node"]
            between_nodes = current_node is None and robot["occupied_edge"] is not None
            if between_nodes:
                occupied = next(
                    (
                        feature["properties"]
                        for feature in graph["features"]
                        if str((feature.get("properties") or {}).get("id"))
                        == robot["occupied_edge"]
                        and "startid" in (feature.get("properties") or {})
                        and "endid" in (feature.get("properties") or {})
                    ),
                    None,
                )
                if occupied is None:
                    raise ValueError("점유 중인 통로가 그래프에 없습니다.")
                start, end = str(occupied["startid"]), str(occupied["endid"])
                candidates = []
                # 현재 pose에서 각 끝점까지의 거리 + 끝점부터의 A* 비용.
                # 임시 pose 노드를 연결한 탐색과 같으며, 실제 그래프 ID만 유지합니다.
                for previous, endpoint in ((start, end), (end, start)):
                    if not any(node == endpoint for node, _ in path_plan.edges[previous]):
                        continue
                    try:
                        path = path_plan.plan(
                            endpoint, target["id"], speed_mps=SIMULATION_SPEED_MPS
                        )
                    except ValueError:
                        continue  # 이 방향으로는 목적지에 도달할 수 없음
                    distance = (
                        math.dist((robot["x"], robot["y"]), path_plan.nodes[endpoint])
                        + path.total_distance_m
                    )
                    candidates.append((distance, [previous, *path.route]))
                if not candidates:
                    raise ValueError("방향성 그래프에서 도달 가능한 경로가 없습니다.")
                node_ids = min(candidates, key=lambda candidate: candidate[0])[1]
            else:
                if current_node is None:
                    raise ValueError("로봇의 현재 노드를 알 수 없습니다.")
                path = path_plan.plan(current_node, target["id"], speed_mps=SIMULATION_SPEED_MPS)
                node_ids = list(path.route)
            edge_ids = find_edge_ids(graph, node_ids)
            # 첫 yaw는 현재 로봇 방향으로 초기화하고, 이후 yaw는 구간 방향으로 계산
            waypoint_yaws = [float(robot["yaw"])]

            for previous_id, current_id in zip(node_ids, node_ids[1:]):
                previous = get_node(previous_id)
                current = get_node(current_id)

                dx = current["x"] - previous["x"]
                dy = current["y"] - previous["y"]

                # 동일 좌표의 노드는 직전 방향 유지
                if math.hypot(dx, dy) > 1e-9:
                    yaw = math.atan2(dy, dx)
                else:
                    yaw = waypoint_yaws[-1]

                waypoint_yaws.append(yaw)

            already_arrived = len(node_ids) == 1

            # 계산과 검증이 모두 성공한 뒤에만 활성 상태를 교체
            self.stop_robot(robot_id)
            robot["navigation_id"] = uuid4().hex
            robot["goal_node"] = str(target["id"])
            self._wait_for_reservation(robot)
            self._retry_waiting(monotonic(), graph, path_plan)
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
        """TODO: Replace with user-defined coordinate movement control."""
        with self._lock:
            graph = load_route_graph()
            path_plan = DistanceAStar(graph)
            x, y = float(x), float(y)
            occupied_node, occupied_edge = self._locate_occupancy(
                graph,
                path_plan.nodes,
                x,
                y,
            )

            robot = self._get_robot(robot_id)
            probe = dict(robot, occupied_node=occupied_node, occupied_edge=occupied_edge)
            resource = self._occupied_resource(probe, graph)
            now = monotonic()
            if any(
                other is not robot and self._occupied_resource(other, graph) == resource
                for other in self._robots.values()
            ) or any(
                row.robot_id != robot["robot_id"] and row.resource == resource and row.end > now
                for row in self._reservations.snapshot()
            ):
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
                }
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
            robot["goal_node"] = None
            robot["navigation_id"] = None
            self._pending.pop(robot["robot_id"], None)
            self._release_schedule(robot)
            # 위치와 점유는 유지한다. route가 없어도 구간 중간에서 재출발 가능.
            robot["route"] = None
        return self._command_response(robot_id, "stop", None)

    def cmd_vel(self, robot_id: str, linear_x: float, angular_z: float) -> dict[str, Any]:
        """TODO: Replace with user-defined velocity command transport."""
        with self._lock:
            robot = self._get_robot(robot_id)
            if robot["goal_node"] is not None:
                if linear_x != 0 or angular_z != 0:
                    raise ValueError("예약 주행 또는 대기 중에는 먼저 정지 명령을 실행해야 합니다.")
                # 선택 변경 등의 정리용 영속도 명령은 예약·대기 상태를 바꾸지 않는다.
            elif robot["status"] != "NAVIGATING":
                robot["status"] = "MOVING" if linear_x or angular_z else "IDLE"
        return {
            "type": "ack",
            "data": self._command_response(
                robot_id,
                "cmd_vel",
                {"linear_x": float(linear_x), "angular_z": float(angular_z)},
            ),
        }

    def advance_mock_robot(
        self,
        robot_id: str,
        dt: float,
        speed_mps: float = SIMULATION_SPEED_MPS,
        *,
        now: float | None = None,
        graph=None,
        nodes=None,
    ) -> None:
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

                index = route["segment_index"]
                resource = edge_key(node_ids[index], node_ids[next_index])
                rows = [
                    row
                    for row in self._reservations.snapshot()
                    if row.robot_id == robot["robot_id"]
                    and row.navigation_id == robot["navigation_id"]
                    and row.segment_index == index
                ]
                edge = next((row for row in rows if row.resource == resource), None)
                destination = next(
                    (row for row in rows if row.resource == node_key(node_ids[next_index])), None
                )
                occupied = any(
                    other is not robot
                    and self._occupied_resource(other, graph)
                    in (resource, node_key(node_ids[next_index]))
                    for other in self._robots.values()
                )
                # 시각만으로 점유를 해제하지 않는다. 남은 주행이 예약을 넘으면 즉시 정지/재예약
                finish = now + distance / speed_mps
                if (
                    edge is None
                    or destination is None
                    or occupied
                    or finish + RESERVATION_MARGIN_S > edge.end + dt + 1e-6
                    or finish + RESERVATION_MARGIN_S > destination.end + dt + 1e-6
                ):
                    self._wait_for_reservation(robot)
                    return
                # 구간 진입 시각 확인 및 해당 시각 이후의 이동량만 허용
                if now < edge.start + RESERVATION_MARGIN_S:
                    return
                remaining = min(
                    remaining,
                    speed_mps
                    * max(
                        0.0,
                        now - (edge.start + RESERVATION_MARGIN_S),
                    ),
                )
                if remaining <= 0:
                    return
                route["phase"] = "moving"

                if distance > 0.0:
                    robot["yaw"] = route["waypoint_yaws"][next_index]

                # 다음 노드까지 도착하고 남은 거리로 계속 진행
                if distance <= remaining:
                    robot["x"] = target_x
                    robot["y"] = target_y
                    robot["current_node"] = str(target_id)
                    robot["occupied_node"] = str(target_id)
                    robot["occupied_edge"] = None
                    route["segment_index"] = next_index
                    remaining -= distance

                    if next_index == len(node_ids) - 1:
                        robot["status"] = "IDLE"
                        robot["route"] = None
                        robot["goal_node"] = None
                        self._release_schedule(robot)
                        return

                else:
                    # 목표 노드 방향으로 remaining만큼 이동
                    ratio = remaining / distance
                    robot["x"] += dx * ratio
                    robot["y"] += dy * ratio

                    # 노드 사이를 이동하는 상태
                    robot["current_node"] = None
                    robot["occupied_node"] = None
                    robot["occupied_edge"] = route["edge_ids"][route["segment_index"]]
                    return


mock_fms = MockFmsStore(reservation_tables["simulation"])
