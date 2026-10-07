"""실제 Robot/ROS 실행과 기존 TrafficManager 사이의 연결부.

경로 선택·예약·대기·양보 정책은 TrafficManager를 그대로 호출한다.
계획용 좌표/상태만 변환하며 Robot의 수신 좌표와 주문 정보는 덮어쓰지 않는다.
"""
from copy import deepcopy
import math
import logging
from time import monotonic

from ..config import (
    REAL_NAVIGATION_SPEED_MPS, REAL_RESERVATION_MARGIN_S,
    REAL_OCCUPANCY_TOLERANCE_M, REAL_POSE_TIMEOUT_S,
)
from ..models.robot import RobotState, NavigationType
from .occupancy import locate_occupancy
from .pathfinding import DistanceAStar
from .reservation import reservation_tables
from .route_graph import load_route_graph
from .traffic_manager import TrafficManager


class RealNavigation:
    def __init__(self, fleet, send_goal, cancel_goal, on_complete, goal_yaws,
                 arrival_distance, *, reservations=None, clock=monotonic):
        self._fleet = fleet
        self._send_goal = send_goal
        self._cancel_goal = cancel_goal
        self._on_complete = on_complete
        self._goal_yaws = goal_yaws
        self._arrival_distance = arrival_distance
        self._clock = clock
        self._robots = {}
        self._traffic = TrafficManager(
            self._robots,
            reservation_tables["real"] if reservations is None else reservations,
            speed_mps=REAL_NAVIGATION_SPEED_MPS,
            safety_margin=REAL_RESERVATION_MARGIN_S,
        )
        self.lock = self._traffic.lock
        self._executing = {}
        self._stopping = {}
        self._requests = {}
        self._cancelled = set()
        self._yielding = set()
        self._request_versions = {}

    def is_active(self, robot_id):
        with self.lock:
            return (robot_id in self._requests or robot_id in self._executing
                    or robot_id in self._stopping or robot_id in self._yielding
                    or robot_id in self._traffic._concession)

    def _sync(self, graph, planner, now):
        """측정 좌표는 보존하고 공통 알고리즘 입력용 위치만 노드에 대응시킨다."""
        valid = True
        for robot in self._fleet.get_all_robots():
            rid = robot.robot_id
            with robot._lock:
                x, y, yaw, received = robot.x, robot.y, robot.yaw, robot.pose_received_at
            fresh = (robot.connected and received is not None
                     and 0 <= now - received <= REAL_POSE_TIMEOUT_S
                     and all(v is not None and math.isfinite(v) for v in (x, y, yaw)))
            row = self._robots.get(rid)
            if not fresh:
                # 연결 해제 후에도 마지막 점유를 지우지 않는다. 알 수 없는 점유로 새 실행 금지.
                if robot.connected or row is not None:
                    valid = False
                continue
            try:
                node, edge = locate_occupancy(
                    graph, planner.nodes, x, y, tolerance_m=REAL_OCCUPANCY_TOLERANCE_M)
            except ValueError:
                valid = False
                continue
            if row is None:
                row = self._robots[rid] = dict(
                    robot_id=rid, goal_node=None, navigation_id=None, route=None,
                    request_order=None, stop_requested=False, status=robot.state.value)
            row.update(x=x, y=y, yaw=yaw, current_node=node,
                       occupied_node=node, occupied_edge=edge)
            if node is not None:
                row["x"], row["y"] = planner.nodes[node]
            if rid not in self._requests and rid not in self._executing and rid not in self._traffic._concession:
                row["status"] = robot.state.value
                # 기존 작업·충전 완료 상태를 IDLE 양보 후보로 오인하지 않는다.
                if (robot.state != RobotState.IDLE or robot.order_id is not None
                        or robot.goal_node is not None):
                    row["stop_requested"] = True
            robot.current_node, robot.occupied_node, robot.occupied_edge = node, node, edge
        return valid

    def stop(self, robot_id, callback=None):
        """Nav2 종료 전에는 계획/예약을 해제하지 않는다. 마지막 요청만 실행한다."""
        with self.lock:
            already_stopping = robot_id in self._stopping
            self._stopping[robot_id] = callback
            if already_stopping:
                return

            def stopped():
                with self.lock:
                    self._executing.pop(robot_id, None)
                    next_step = self._stopping.pop(robot_id, None)
                    if next_step is not None:
                        try:
                            next_step()
                        except (ValueError, RuntimeError):
                            robot = self._fleet.get_robot(robot_id)
                            if robot.connected and robot.state != RobotState.EMERGENCY_STOP:
                                robot.set_state(RobotState.PAUSED)
                            logging.getLogger(__name__).exception("정지 후 내비게이션 처리 실패: %s", robot_id)
            self._cancel_goal(robot_id, callback=stopped)

    def cancel_after_stop(self, robot_id):
        with self.lock:
            self._request_versions[robot_id] = self._request_versions.get(robot_id, 0) + 1
            self._cancelled.add(robot_id)
            self._requests.pop(robot_id, None)
            graph = load_route_graph()
            if self._sync(graph, DistanceAStar(graph), self._clock()):
                self._clear_cancelled()
            self._publish()

    def _clear_cancelled(self):
        for rid in self._cancelled:
            if rid in self._robots:
                self._traffic.cancel_navigation_after_stop(rid)
            robot = self._fleet.get_robot(rid)
            robot.route = None
            robot.next_node = robot.next_edge = None
        self._cancelled.clear()

    def request(self, robot_id, node_id, navigation_type, *, _request_version=None):
        with self.lock:
            if _request_version is None:
                _request_version = self._request_versions.get(robot_id, 0) + 1
                self._request_versions[robot_id] = _request_version
            elif self._request_versions.get(robot_id) != _request_version:
                return
            graph = load_route_graph()
            planner = DistanceAStar(graph)
            if str(node_id) not in planner.nodes:
                raise ValueError(f"존재하지 않는 route node: {node_id}")
            robot = self._fleet.get_robot(robot_id)
            if robot is None or not robot.connected:
                raise ValueError(f"Robot이 연결되어 있지 않습니다: {robot_id}")
            if robot.state == RobotState.EMERGENCY_STOP:
                raise ValueError(f"비상정지 상태입니다: {robot_id}")
            if not self._sync(graph, planner, self._clock()):
                raise ValueError("실제 로봇의 최신 위치와 점유를 확인할 수 없습니다.")
            self._clear_cancelled()
            # request_navigation_after_stop 내부에서도 retry_waiting이 호출된다.
            # 종료되는 양보 실행이 있으면 해당 실행 종료 뒤 동일 요청을 접수한다.
            affected = self._ending_concessions(robot_id)
            if affected:
                self.stop(affected[0], lambda: self.request(
                    robot_id, node_id, navigation_type, _request_version=_request_version))
                return
            self._traffic.request_navigation_after_stop(
                robot_id, str(node_id), now=self._clock(), graph=graph)
            robot.goal_node = str(node_id)
            robot.navigation_type = navigation_type
            robot.set_state(RobotState.WAITING)
            self._requests[robot_id] = (str(node_id), navigation_type)
            if self._robots[robot_id]["route"] is None and self._robots[robot_id]["goal_node"] is None:
                self._robots[robot_id]["status"] = "WAITING"
            self._publish()

    def _ending_concessions(self, replacing=None):
        # 공통 서비스의 양보 종료 조건을 실행 종료와 연결한다. 선택 정책은 변경하지 않는다.
        return [rid for rid, maneuver in self._traffic._concession.items()
                if rid in self._executing and (
                    maneuver["priority"] == replacing
                    or self._robots[maneuver["priority"]]["goal_node"] is None
                    or self._robots[maneuver["priority"]]["navigation_id"] != maneuver["navigation_id"])]

    def _publish(self):
        rows = self._traffic._reservations.snapshot()
        for rid, state in self._robots.items():
            robot = self._fleet.get_robot(rid)
            robot.navigation_id = state["navigation_id"]
            robot.reserved_nodes = list(dict.fromkeys(
                r.resource[1] for r in rows if r.robot_id == rid and r.resource[0] == "node"))
            # 외부 표시에는 원래 그래프 edge ID를 유지한다.
            route = state["route"]
            robot.reserved_edges = list(route["edge_ids"]) if route and any(
                r.robot_id == rid and r.resource[0] == "edge" for r in rows) else []
            if rid not in self._requests and rid not in self._traffic._concession:
                if rid in self._yielding:
                    self._yielding.discard(rid)
                    robot.route = None
                    robot.next_node = robot.next_edge = None
                    if robot.connected and robot.state not in (RobotState.EMERGENCY_STOP, RobotState.PAUSED):
                        robot.set_state(RobotState.IDLE)
                continue
            robot.route = deepcopy(state["route"])
            route = state["route"]
            robot.next_node = route["node_ids"][route["segment_index"] + 1] if route else None
            robot.next_edge = route["edge_ids"][route["segment_index"]] if route else None
            if robot.connected and robot.state not in (RobotState.EMERGENCY_STOP, RobotState.PAUSED):
                robot.set_state(RobotState.MOVING if rid in self._executing else RobotState.WAITING)

    def _replan_after_stop(self, robot_id):
        graph = load_route_graph()
        if not self._sync(graph, DistanceAStar(graph), self._clock()):
            # 최신 위치가 올 때까지 기존 예약과 점유를 유지한다.
            return
        if robot_id in self._robots and self._robots[robot_id]["route"] is not None:
            self._traffic.wait_for_reservation_after_stop(robot_id)

    def tick(self):
        with self.lock:
            if not self._cancelled and not self._requests and not self._traffic.has_active_requests():
                return
            graph = load_route_graph()
            planner = DistanceAStar(graph)
            now = self._clock()
            if not self._sync(graph, planner, now):
                for rid in list(self._executing):
                    if rid not in self._stopping:
                        self.stop(rid)
                return
            self._clear_cancelled()
            affected = self._ending_concessions()
            if affected:
                for rid in affected:
                    if rid not in self._stopping:
                        self.stop(rid)
                return
            if not self._stopping:
                self._traffic.retry_waiting(now, graph, planner)
            for rid, state in list(self._robots.items()):
                robot = self._fleet.get_robot(rid)
                if not robot.connected or robot.state in (RobotState.EMERGENCY_STOP, RobotState.PAUSED):
                    continue
                if rid in self._stopping or (self._stopping and rid not in self._executing):
                    continue
                route = state["route"]
                if route is None:
                    # 같은 노드 요청도 기존 최종 방향 정렬과 Nav2 완료 확인을 유지한다.
                    if rid in self._requests and state["goal_node"] is None and rid not in self._executing:
                        self._send(rid, self._requests[rid][0], None, planner)
                    continue
                if route.get("departure_at") is None:
                    continue
                target = route["node_ids"][route["segment_index"] + 1]
                # 기존 도착 허용 거리까지의 남은 시간을 실제 수신 좌표로 계산한다.
                distance = math.dist((robot.x, robot.y), planner.nodes[target])
                arrival = now + max(0., distance - self._arrival_distance) / self._traffic.speed_mps
                permission = self._traffic.check_segment_permission(
                    rid, now=now, expected_arrival_at=arrival, graph=graph)
                if permission.decision == "replan":
                    if rid in self._executing:
                        self.stop(rid, lambda rid=rid: self._replan_after_stop(rid))
                    else:
                        self._traffic.wait_for_reservation_after_stop(rid)
                elif permission.decision == "allowed" and rid not in self._executing:
                    self._send(rid, target, route["segment_index"], planner)
            self._publish()

    def _send(self, rid, target, segment_index, planner):
        robot = self._fleet.get_robot(rid)
        state = self._robots[rid]
        x, y = planner.nodes[target]
        yaw = float(robot.yaw)
        if segment_index is not None:
            route = state["route"]
            # 기존 waypoint 방향 규칙: 중간 노드는 다음 노드 방향, 마지막은 진입 방향.
            if segment_index + 2 < len(route["node_ids"]):
                nx, ny = planner.nodes[route["node_ids"][segment_index + 2]]
                yaw = math.atan2(ny - y, nx - x)
            else:
                px, py = planner.nodes[route["node_ids"][segment_index]]
                yaw = math.atan2(y - py, x - px)
        final = rid in self._requests and target == self._requests[rid][0] and rid not in self._traffic._concession
        if final:
            yaw = (float(robot.yaw) if robot.navigation_type == NavigationType.RETURN
                   else self._goal_yaws.get(target, yaw))
        if rid not in self._requests:
            self._yielding.add(rid)
        self._executing[rid] = (state["navigation_id"], target, segment_index, final)
        try:
            self._send_goal(robot_id=rid, waypoints=[(x, y, yaw)])
        except (ValueError, RuntimeError):
            self._executing.pop(rid, None)
            robot.set_state(RobotState.PAUSED)
            self.cancel_after_stop(rid)
            raise
        if rid in self._executing:
            robot.set_state(RobotState.MOVING)

    def on_result(self, robot_id, succeeded):
        """구간 결과만 소비한다. 원래 목적지 도착 때만 기존 후속 처리 호출."""
        with self.lock:
            execution = self._executing.pop(robot_id, None)
            if execution is None:
                return
            navigation_id, target, segment_index, final = execution
            state = self._robots[robot_id]
            if navigation_id != state["navigation_id"]:
                return
            robot = self._fleet.get_robot(robot_id)
            graph = load_route_graph()
            planner = DistanceAStar(graph)
            if (not succeeded or not self._sync(graph, planner, self._clock())
                    or math.dist((robot.x, robot.y), planner.nodes[target]) > self._arrival_distance):
                robot.set_state(RobotState.PAUSED)
                self.cancel_after_stop(robot_id)
                return
            # 계획용 상태만 노드 좌표로 대응시킨다. 수신 Robot 좌표는 보존한다.
            state["x"], state["y"] = planner.nodes[target]
            if segment_index is not None:
                self._traffic.confirm_node_arrival(robot_id, target)
            robot.current_node = robot.occupied_node = target
            robot.occupied_edge = None
            if final:
                robot.next_node = robot.next_edge = None
                self._requests.pop(robot_id, None)
                # TrafficManager가 비운 goal_node 대신 실제 Robot의 원래 목적지를 사용한다.
                self._on_complete(robot_id)
            elif state["route"] is None and robot_id not in self._traffic._concession:
                robot.route = None
                robot.set_state(RobotState.IDLE)
            self._publish()
