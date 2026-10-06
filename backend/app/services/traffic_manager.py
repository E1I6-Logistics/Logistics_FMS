"""예약, 대기 재시도, 교착 해소 및 구간 주행 허가 정책.

ROS, mock 데이터, 좌표 보간에 의존하지 않는다. 호출자가 그래프, 시각 및
점유 상태를 제공한다. 시각은 예약표와 동일한 monotonic 기준을 사용한다.
robots는 robot_id를 키로 하는 상태 dict이며 필요한 필드는 doc/traffic_manager.md 참고.
상태 갱신과 정책 호출은 lock으로 함께 보호해야 한다.

*_after_stop / confirm_node_arrival API는 호출자가 실제 정지/도착을 확인한 뒤 호출한다.
이 서비스는 정지 명령을 보내거나 실제 정지를 확인하지 않는다.
"""

from copy import copy, deepcopy
from dataclasses import dataclass
import math
from threading import RLock
from typing import Any, Literal
from uuid import uuid4

from .occupancy import occupied_resource
from .pathfinding import DistanceAStar
from .reservation import ReservationTable, build_schedule, node_key, edge_key
from .route_graph import find_edge_ids


@dataclass(frozen=True)
class SegmentPermission:
    decision: Literal["allowed", "waiting", "replan"]
    reason: str


class TrafficManager:
    def __init__(self, robots: dict[str, dict[str, Any]], reservations=None, *,
                 speed_mps: float, safety_margin: float):
        if not all(math.isfinite(v) and v > 0 for v in (speed_mps, safety_margin)):
            raise ValueError("속도와 안전 여유는 유한한 양수여야 합니다.")
        self._robots = robots
        self._reservations = reservations if reservations is not None else ReservationTable()
        self.speed_mps = speed_mps
        self.safety_margin = safety_margin
        self.lock = RLock()
        self._pending: dict[str, None] = {}
        self._concession: dict[str, dict] = {}
        self._request_sequence = 0

    def reset_after_stop(self):
        """전체 실행 종료 및 점유 보존이 확인된 상태에서 계획만 초기화한다."""
        with self.lock:
            for robot in self._robots.values():
                self.cancel_navigation_after_stop(robot["robot_id"])
            requests = {(row.robot_id, row.navigation_id) for row in self._reservations.snapshot()}
            for robot_id, navigation_id in requests:
                self._reservations.release_request(robot_id, navigation_id)
            self._pending.clear()
            self._concession.clear()
            self._request_sequence = 0

    def has_active_requests(self) -> bool:
        with self.lock:
            return bool(self._concession) or any(
                robot["goal_node"] is not None for robot in self._robots.values())

    def request_navigation_after_stop(self, robot_id, goal_node, *, now, graph):
        """기존 실행 정지와 점유 갱신 후 새 요청을 접수하고 예약한다."""
        with self.lock:
            self._validate_time(now)
            planner = DistanceAStar(graph)
            goal_node = str(goal_node)
            if goal_node not in planner.nodes:
                raise ValueError("목적지 노드가 존재하지 않습니다.")
            robot = self._robots[robot_id]
            occupied_resource(robot, graph)
            self.cancel_navigation_after_stop(robot_id)
            robot["stop_requested"] = False
            self._request_sequence += 1
            robot["request_order"] = self._request_sequence
            robot["navigation_id"] = uuid4().hex
            robot["goal_node"] = goal_node
            self._wait_for_reservation(robot)
            self._retry_waiting(now, graph, planner)

    def cancel_navigation_after_stop(self, robot_id):
        """정지가 확인된 요청을 취소한다. 실제 위치·점유는 남긴다."""
        with self.lock:
            robot = self._robots[robot_id]
            robot["status"] = "IDLE"
            robot["goal_node"] = None
            robot["navigation_id"] = None
            robot["request_order"] = None
            robot["stop_requested"] = True
            self._concession.pop(robot_id, None)
            self._pending.pop(robot_id, None)
            self._release_schedule(robot)
            robot["route"] = None

    def wait_for_reservation_after_stop(self, robot_id):
        with self.lock:
            self._wait_for_reservation(self._robots[robot_id])

    def retry_waiting(self, now, graph, planner=None):
        """정지 중인 대기 요청을 재계획한다. 양보 종료 시 실행 정지는 호출자 책임."""
        with self.lock:
            self._validate_time(now)
            self._retry_waiting(now, graph, planner or DistanceAStar(graph))

    def confirm_node_arrival(self, robot_id, node_id):
        """실행기가 좌표를 갱신하고 도착을 확인한 뒤 구간 진행을 반영한다."""
        with self.lock:
            robot = self._robots[robot_id]
            route = robot["route"]
            if route is None:
                raise ValueError("진행 중인 경로가 없습니다.")
            index = route["segment_index"] + 1
            if index >= len(route["node_ids"]) or str(node_id) != route["node_ids"][index]:
                raise ValueError("현재 구간의 도착 노드와 일치하지 않습니다.")
            robot["current_node"] = str(node_id)
            robot["occupied_node"] = str(node_id)
            robot["occupied_edge"] = None
            route["segment_index"] = index
            if index == len(route["node_ids"]) - 1:
                self._finish_route(robot)

    def confirm_edge_occupancy(self, robot_id):
        with self.lock:
            robot = self._robots[robot_id]
            route = robot["route"]
            if route is None:
                raise ValueError("진행 중인 경로가 없습니다.")
            robot["current_node"] = None
            robot["occupied_node"] = None
            robot["occupied_edge"] = route["edge_ids"][route["segment_index"]]

    def validate_manual_velocity(self, robot_id, linear_x, angular_z) -> bool:
        """수동 명령 가능 여부. 예약 중 영속도는 허용하지만 False로 상태 보존 지시."""
        with self.lock:
            robot = self._robots[robot_id]
            if robot["goal_node"] is not None or robot_id in self._concession:
                if linear_x != 0 or angular_z != 0:
                    raise ValueError("예약 주행 또는 대기 중에는 먼저 정지 명령을 실행해야 합니다.")
                return False
            return True

    def is_resource_blocked(self, robot_id, resource, *, now, graph) -> bool:
        with self.lock:
            self._validate_time(now)
            return any(other["robot_id"] != robot_id and occupied_resource(other, graph) == resource
                       for other in self._robots.values()) or any(
                row.robot_id != robot_id and row.resource == resource and row.end > now
                for row in self._reservations.snapshot())

    @staticmethod
    def _validate_time(value):
        if not math.isfinite(value) or value < 0:
            raise ValueError("시각은 유한한 0 이상의 값이어야 합니다.")

    def check_segment_permission(self, robot_id, *, now, expected_arrival_at, graph) -> SegmentPermission:
        """예약·출발시각·실제 점유·예상 도착을 검사한다. 상태/예약을 변경하지 않는다.

        expected_arrival_at은 실행기가 계산한다. tick 기반 실행기는 해당 tick에서
        이동할 거리를 반영하고, 실제 실행기는 관측 기반 잔여 이동 시간을 반영한다.
        replan은 즉시 예약 해제를 뜻하지 않는다. 정지 확인 후 대기로 전환해야 한다.
        """
        with self.lock:
            self._validate_time(now)
            self._validate_time(expected_arrival_at)
            robot = self._robots[robot_id]
            route = robot["route"]
            if route is None or route.get("departure_at") is None:
                return SegmentPermission("replan", "missing_schedule")
            index = route["segment_index"]
            nodes = route["node_ids"]
            if not 0 <= index < len(nodes) - 1:
                raise ValueError("경로 진행 인덱스가 올바르지 않습니다.")
            resource = edge_key(nodes[index], nodes[index + 1])
            target = node_key(nodes[index + 1])
            rows = [row for row in self._reservations.snapshot()
                    if row.robot_id == robot_id and row.navigation_id == robot["navigation_id"]
                    and row.segment_index == index]
            edge = next((row for row in rows if row.resource == resource), None)
            destination = next((row for row in rows if row.resource == target), None)
            if edge is None or destination is None:
                return SegmentPermission("replan", "missing_reservation")
            if now <= route["segment_departures"][index]:
                return SegmentPermission("waiting", "departure_time")
            if any(other is not robot and occupied_resource(other, graph) in (resource, target)
                   for other in self._robots.values()):
                return SegmentPermission("replan", "occupied")
            if (expected_arrival_at + self.safety_margin > edge.end + 1e-6
                    or expected_arrival_at + self.safety_margin > destination.end + 1e-6):
                return SegmentPermission("replan", "schedule_overrun")
            return SegmentPermission("allowed", "reserved")

    def _release_schedule(self, robot):
        # 호출자는 실행 종료/정지를 확인해야 한다. 위치·점유는 유지한다.
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
            resource = occupied_resource(other, graph)
            route = other["route"]
            scheduled = route is not None and route.get("departure_at") is not None
            # 예정 시각이 지나도 실제 점유가 남아 있으면 해제하지 않는다.
            until = max((row.end for row in others
                         if row.robot_id == other["robot_id"] and row.resource == resource
                         and row.start <= now < row.end), default=math.inf) if scheduled else math.inf
            blocked.setdefault(resource, []).append((max(0., now - self.safety_margin), until))

        resource = occupied_resource(robot, graph)
        plan = planner.plan_timed(
            self._concession.get(robot["robot_id"], {}).get("node", robot["goal_node"]),
            (robot["x"], robot["y"]), robot["occupied_node"],
            resource[1:] if resource[0] == "edge" else None,
            blocked=blocked, now=now, speed_mps=self.speed_mps,
            safety_margin=self.safety_margin,
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
            departure_at=departure, speed_mps=self.speed_mps,
            safety_margin=self.safety_margin, segment_departures=departures,
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
        trial.lock = RLock()
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
        occupied = {rid: occupied_resource(self._robots[rid], graph) for rid in waiting}
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
