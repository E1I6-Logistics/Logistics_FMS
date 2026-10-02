"""Deterministic, in-memory frontend contract data.

No database, path planning, robot communication, or equipment control belongs
in this module. Replace each command TODO with project-specific control logic.
"""

from __future__ import annotations

from copy import copy, deepcopy
from datetime import datetime, timezone
from time import monotonic
from uuid import uuid4
from threading import RLock
from typing import Any

from ..schemas.robot import normalize_robot_id, to_ui_robot_id
from .map_service import world_to_pixel
from .route_graph import get_node, load_route_graph, find_edge_ids, locate_current_node
from .pathfinding import DistanceAStar
from .reservation import ReservationTable, build_schedule, node_key, edge_key, reservation_tables

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
        self._concession: dict[str, dict] = {}
        self._request_sequence = 0
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
            self._concession.clear()
            self._request_sequence = 0
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
            if (str(props.get("id")) == robot["occupied_edge"]
                    and "startid" in props and "endid" in props):
                return edge_key(props["startid"], props["endid"])
        raise ValueError("실제 점유 위치를 확인할 수 없습니다.")

    def _release_schedule(self, robot):
        # 시뮬레이션은 동일 잠금 안에서 즉시 정지하며 위치·점유는 유지한다.
        requests = {row.navigation_id for row in self._reservations.snapshot()
                    if row.robot_id == robot["robot_id"]}
        for navigation_id in requests:
            self._reservations.release_request(robot["robot_id"], navigation_id)

    def _wait_for_reservation(self, robot):
        robot["status"] = "WAITING"
        if robot["route"] is not None:
            robot["route"]["phase"] = "waiting"
            robot["route"]["departure_at"] = None
        self._release_schedule(robot)
        self._pending.setdefault(robot["robot_id"], None)

    def _try_schedule(self, robot, now, graph, planner):
        others = [row for row in self._reservations.snapshot()
                  if row.robot_id != robot["robot_id"]]
        blocked = {}
        for row in others:
            blocked.setdefault(row.resource, []).append((row.start, row.end))
        for other in self._robots.values():
            if other is robot:
                continue
            resource = self._occupied_resource(other, graph)
            route = other["route"]
            scheduled = route is not None and route.get("departure_at") is not None
            # 예정 시각이 지나도 실제 점유가 남아 있으면 해제하지 않는다.
            until = max((row.end for row in others
                         if row.robot_id == other["robot_id"] and row.resource == resource
                         and row.start <= now < row.end), default=math.inf) if scheduled else math.inf
            blocked.setdefault(resource, []).append((max(0., now - RESERVATION_MARGIN_S), until))

        resource = self._occupied_resource(robot, graph)
        plan = planner.plan_timed(
            self._concession.get(robot["robot_id"], {}).get("node", robot["goal_node"]),
            (robot["x"], robot["y"]), robot["occupied_node"],
            resource[1:] if resource[0] == "edge" else None,
            blocked=blocked, now=now, speed_mps=SIMULATION_SPEED_MPS,
            safety_margin=RESERVATION_MARGIN_S,
        )
        if plan is None:
            return False
        node_ids, departures = plan["node_ids"], plan["segment_departures"]
        edge_ids = find_edge_ids(graph, node_ids)
        waypoint_yaws = [float(robot["yaw"])]
        for start, end in zip(node_ids, node_ids[1:]):
            ax, ay = planner.nodes[start]
            bx, by = planner.nodes[end]
            waypoint_yaws.append(math.atan2(by - ay, bx - ax)
                                 if math.hypot(bx - ax, by - ay) > 1e-9 else waypoint_yaws[-1])
        departure = departures[0] if departures else now
        batch = build_schedule(
            robot["robot_id"], robot["navigation_id"], node_ids, planner.nodes,
            (robot["x"], robot["y"]), robot["occupied_node"], now=now,
            departure_at=departure, speed_mps=SIMULATION_SPEED_MPS,
            safety_margin=RESERVATION_MARGIN_S, segment_departures=departures,
        )
        if not self._reservations.replace_request(robot["robot_id"], robot["navigation_id"], batch):
            return False
        # 경로와 시간표를 예약 성공 후 함께 교체한다.
        if not departures:
            self._finish_route(robot)
        else:
            robot["route"] = {
                "node_ids": node_ids, "edge_ids": edge_ids, "waypoint_yaws": waypoint_yaws,
                "segment_index": 0, "phase": "ready", "departure_at": departure,
                "segment_departures": departures,
            }
            robot["status"] = "WAITING" if departure > now else "NAVIGATING"
        return True

    # 대피 도착은 원래 명령의 완료가 아니므로, 실제 점유를 유지
    def _finish_route(self, robot):
        robot["route"] = None
        self._release_schedule(robot)
        if robot["robot_id"] in self._concession:
            robot["status"] = "WAITING"
            self._pending.setdefault(robot["robot_id"], None)
        else:
            robot["goal_node"] = None
            robot["request_order"] = None
            robot["status"] = "IDLE"

    #양보 후보 검증은 실제 로봇/공용 예약표를 변경하지 않음
    def _planning_copy(self):
        trial = copy(self)
        trial._robots = deepcopy(self._robots)
        trial._pending = dict(self._pending)
        trial._concession = deepcopy(self._concession)
        trial._reservations = ReservationTable()
        rows = self._reservations.snapshot()
        for robot_id, navigation_id in {(r.robot_id, r.navigation_id) for r in rows}:
            trial._reservations.try_commit(robot_id, navigation_id, tuple(
                r for r in rows if (r.robot_id, r.navigation_id) == (robot_id, navigation_id)))
        return trial

    # 진행 중인 양보는 완료/취소까지 유지하여 왕복 양보를 방지
    def _resolve_deadlock(self, now, graph, planner):
        if self._concession or not self._pending:
            return
        waiting = sorted(self._pending, key=lambda rid: self._robots[rid]["request_order"])
        parked = [rid for rid, robot in self._robots.items()
                  if robot["status"] == "IDLE" and robot["goal_node"] is None
                  and robot["route"] is None and not robot["stop_requested"]]
        occupied = {rid: self._occupied_resource(self._robots[rid], graph) for rid in waiting}
        dependencies = {}
        for rid in waiting:
            trial = self._planning_copy()
            for other in waiting:
                if other != rid:
                    trial._robots.pop(other)
                    trial._release_schedule(self._robots[other])
            robot = trial._robots[rid]

            # 현재 검사 방식에서 교착 관계를 확인하지 못한 경우 (더 있을 수도..)
            if not trial._try_schedule(robot, now, graph, planner) or robot["route"] is None:
                dependencies[rid] = set()
                continue
            path = robot["route"]["node_ids"]
            resources = {node_key(n) for n in path}
            resources.update(edge_key(a, b) for a, b in zip(path, path[1:]))
            dependencies[rid] = {other for other in waiting if other != rid and occupied[other] in resources}

        def reachable(start):
            seen, todo = set(), list(dependencies[start])
            while todo:
                rid = todo.pop()
                if rid not in seen:
                    seen.add(rid)
                    todo.extend(dependencies[rid] - seen)
            return seen

        reach = {rid: reachable(rid) for rid in waiting}
        for priority in waiting:
            cycle = [rid for rid in waiting if rid != priority
                     and rid in reach[priority] and priority in reach[rid]]
            # 이동 요청이 없어도 이 로봇의 점유를 제외하면 길이 열리는지 검사
            blockers = []
            for rid in parked:
                trial = self._planning_copy()
                trial._robots.pop(rid)
                trial._release_schedule(self._robots[rid])
                if trial._try_schedule(trial._robots[priority], now, graph, planner):
                    blockers.append(rid)
            if not cycle and not blockers:
                continue
            # 같은 교착 집합에서는 최초 명령이 우선이며 후순위만 양보
            if any(self._robots[rid]["request_order"] < self._robots[priority]["request_order"] for rid in cycle):
                continue
            candidates = []
            for concession in [*reversed(cycle), *blockers]:
                robot = self._robots[concession]
                for node in planner.nodes:
                    if node == robot["occupied_node"]:
                        continue
                    trial = self._planning_copy()
                    trial._concession[concession] = {
                        "node": node, "priority": priority,
                        "navigation_id": self._robots[priority]["navigation_id"],
                    }
                    mover = trial._robots[concession]
                    if mover["goal_node"] is None:
                        mover["navigation_id"] = uuid4().hex
                    if not trial._try_schedule(mover, now, graph, planner):
                        continue
                    route = mover["route"]
                    if route is None or not trial._try_schedule(trial._robots[priority], now, graph, planner):
                        continue
                    # 유휴 로봇은 대피 지점에서 정차하므로 원래 목적지 재개 검사가 없다.
                    if robot["goal_node"] is not None:
                        # 우선 로봇의 목적지 정차 이후에도 원래 목적지로 복귀 가능해야 한다.
                        resume = trial._planning_copy()
                        leader = resume._robots[priority]
                        leader["x"], leader["y"] = planner.nodes[leader["goal_node"]]
                        leader["occupied_node"] = leader["goal_node"]
                        leader["occupied_edge"] = None
                        leader["route"] = None
                        resume._release_schedule(leader)
                        follower = resume._robots[concession]
                        follower["x"], follower["y"] = planner.nodes[node]
                        follower["occupied_node"], follower["occupied_edge"] = node, None
                        follower["route"] = None
                        resume._concession.pop(concession)
                        resume._release_schedule(follower)
                        can_resume = resume._try_schedule(follower, now, graph, planner)
                        remaining = [rid for rid in cycle if rid != concession]

                        while not can_resume and remaining:
                            progressed = False
                            for rid in list(remaining):
                                other = resume._robots[rid]
                                goal = other["goal_node"]
                                if not resume._try_schedule(other, now, graph, planner):
                                    continue
                                other["x"], other["y"] = planner.nodes[goal]
                                other["occupied_node"], other["occupied_edge"] = goal, None
                                other["route"] = None
                                resume._release_schedule(other)
                                remaining.remove(rid)
                                progressed = True
                            can_resume = resume._try_schedule(follower, now, graph, planner)
                            if not progressed:
                                break
                        if not can_resume:
                            continue
                    points = [(robot["x"], robot["y"])] + [planner.nodes[n] for n in route["node_ids"][1:]]
                    distance = sum(math.dist(a, b) for a, b in zip(points, points[1:]))
                    candidates.append((distance, -(robot["request_order"] or 0), node, concession, trial._concession[concession]))
            for _, _, _, concession, maneuver in sorted(candidates):
                robot = self._robots[concession]
                previous_navigation = robot["navigation_id"]
                if robot["goal_node"] is None:
                    robot["navigation_id"] = uuid4().hex
                self._concession[concession] = maneuver
                if self._try_schedule(robot, now, graph, planner):
                    self._pending.pop(concession, None)
                    return
                self._concession.pop(concession)
                robot["navigation_id"] = previous_navigation

    def _retry_waiting(self, now, graph, planner):
        for rid, maneuver in list(self._concession.items()):
            leader = self._robots[maneuver["priority"]]
            if leader["goal_node"] is None or leader["navigation_id"] != maneuver["navigation_id"]:
                # 우선 명령 완료/취소/교체 시 현재 위치에서 원래 목적지를 재개
                self._concession.pop(rid)
                robot = self._robots[rid]
                if robot["goal_node"] is None:
                    self._finish_route(robot)
                    self._pending.pop(rid, None)
                else:
                    self._wait_for_reservation(robot)
        for robot_id in sorted(self._pending, key=lambda rid: self._robots[rid]["request_order"] or math.inf):
            robot = self._robots[robot_id]
            if robot["goal_node"] is None and robot_id not in self._concession:
                self._pending.pop(robot_id, None)
            elif robot_id in self._concession and robot["occupied_node"] == self._concession[robot_id]["node"]:
                continue
            elif self._try_schedule(robot, now, graph, planner):
                self._pending.pop(robot_id, None)
        self._resolve_deadlock(now, graph, planner)

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
            if not self._concession and not any(robot["goal_node"] is not None for robot in self._robots.values()):
                return
            graph = load_route_graph()
            planner = DistanceAStar(graph)
            self._retry_waiting(now, graph, planner)
            for robot_id in self._robots:
                self.advance_mock_robot(robot_id, elapsed, now=now, graph=graph, nodes=planner.nodes)
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

    
    def navigate_to_node(self, robot_id: str, node_id: str | int) -> dict[str, Any]:
        """TODO: Replace with user-defined path planning and node movement."""
        with self._lock:
            robot = self._get_robot(robot_id)
            target = get_node(node_id)

            graph = load_route_graph()
            path_plan = DistanceAStar(graph)
            self._occupied_resource(robot, graph)
            # 시뮬레이션은 현재 위치에서 즉시 정지한 뒤 새 요청을 탐색한다.
            self.stop_robot(robot_id)
            # 명시적 정지 명령 구분
            robot["stop_requested"] = False
            # 명령 접수 순서 부여
            self._request_sequence += 1
            robot["request_order"] = self._request_sequence
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
                graph, path_plan.nodes, x, y,
            )

            robot = self._get_robot(robot_id)
            probe = dict(robot, occupied_node=occupied_node, occupied_edge=occupied_edge)
            resource = self._occupied_resource(probe, graph)
            now = monotonic()
            if any(other is not robot and self._occupied_resource(other, graph) == resource
                   for other in self._robots.values()) or any(
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
                    "stop_requested": False,
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
            robot["request_order"] = None
            robot["stop_requested"] = True
            self._concession.pop(robot["robot_id"], None)
            self._pending.pop(robot["robot_id"], None)
            self._release_schedule(robot)
            # 위치와 점유는 유지한다. route가 없어도 구간 중간에서 재출발 가능.
            robot["route"] = None
        return self._command_response(robot_id, "stop", None)

    def cmd_vel(self, robot_id: str, linear_x: float, angular_z: float) -> dict[str, Any]:
        """TODO: Replace with user-defined velocity command transport."""
        with self._lock:
            robot = self._get_robot(robot_id)
            if robot["goal_node"] is not None or robot["robot_id"] in self._concession:
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

                index = route["segment_index"]
                resource = edge_key(node_ids[index], node_ids[next_index])
                rows = [row for row in self._reservations.snapshot()
                        if row.robot_id == robot["robot_id"] and row.navigation_id == robot["navigation_id"]
                        and row.segment_index == index]
                edge = next((row for row in rows if row.resource == resource), None)
                destination = next((row for row in rows if row.resource == node_key(node_ids[next_index])), None)
                
                # 계획된 대기와 재예약 대기 구분
                if edge is None or destination is None:
                    self._wait_for_reservation(robot)
                    return
                departure = route["segment_departures"][index]
                if now <= departure:
                    robot["status"] = "WAITING"
                    route["phase"] = "waiting"
                    return  # 계획된 대기: 예약과 점유를 유지한다.
                remaining = min(remaining, speed_mps * (now - departure))
                if remaining <= 0:
                    return
                occupied = any(other is not robot and self._occupied_resource(other, graph)
                               in (resource, node_key(node_ids[next_index])) for other in self._robots.values())
                # 이번 tick의 허용 이동량을 제외한 잔여 이동도 시간표 안에 들어와야 한다.
                finish = now + (distance - remaining) / speed_mps
                if (occupied or finish + RESERVATION_MARGIN_S > edge.end + 1e-6
                        or finish + RESERVATION_MARGIN_S > destination.end + 1e-6):
                    self._wait_for_reservation(robot)
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
                    robot["current_node"] = str(target_id)
                    robot["occupied_node"] = str(target_id)
                    robot["occupied_edge"] = None
                    route["segment_index"] = next_index
                    remaining -= distance

                    if next_index == len(node_ids) - 1:
                        self._finish_route(robot)
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
