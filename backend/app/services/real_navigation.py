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
    REAL_ARRIVAL_CONFIRM_TIMEOUT_S, REAL_CANCEL_TIMEOUT_S,
)
from ..models.robot import RobotState, NavigationType
from .occupancy import locate_occupancy, occupied_resource
from .pathfinding import DistanceAStar
from .reservation import reservation_tables, edge_key, node_key
from .route_graph import load_route_graph
from .traffic_manager import TrafficManager


def measured_distance(robot, target, now):
    """계획용으로 보정한 좌표가 아닌 실제 수신 좌표로 거리를 검증한다."""
    with robot._lock:
        x, y, received = robot.x, robot.y, robot.pose_received_at
    if not robot.connected:
        raise ValueError("robot_offline")
    if received is None or not math.isfinite(received) or not 0 <= now - received <= REAL_POSE_TIMEOUT_S:
        raise ValueError("pose_stale_or_missing")
    if any(value is None or not math.isfinite(value) for value in (x, y, *target)):
        raise ValueError("pose_or_target_invalid")
    return math.dist((x, y), target)


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
        self._arrival_observed = {}
        self._arrivals = {}
        self._stop_deadlines = {}
        self._sync_errors = {}
        self._feedback = {}
        self._hold = {}
        self._lookahead_decisions = {}
        self._resume_pending = set()
        self._deferred_requests = {}

    def _sync(self, graph, planner, now):
        """측정 좌표는 보존하고 공통 알고리즘 입력용 위치만 노드에 대응시킨다."""
        valid = True
        previous_errors = self._sync_errors
        self._sync_errors = {}
        for robot in self._fleet.get_all_robots():
            rid = robot.robot_id
            with robot._lock:
                x, y, yaw, received = robot.x, robot.y, robot.yaw, robot.pose_received_at
            fresh = (robot.connected and received is not None
                     and math.isfinite(received) and 0 <= now - received <= REAL_POSE_TIMEOUT_S
                     and all(v is not None and math.isfinite(v) for v in (x, y, yaw)))
            row = self._robots.get(rid)
            if not fresh:
                # 연결 해제 후에도 마지막 점유를 지우지 않는다. 알 수 없는 점유로 새 실행 금지.
                if robot.connected or row is not None:
                    valid = False
                    self._sync_errors[rid] = "robot_offline" if not robot.connected else "pose_stale_or_invalid"
                continue
            edge = None
            try:
                try:
                    # 큰 점유 허용 거리에서 Edge 중간을 인접 Node로 먼저 오인하지 않는다.
                    node, edge = locate_occupancy(
                        graph, planner.nodes, x, y,
                        tolerance_m=min(REAL_OCCUPANCY_TOLERANCE_M, self._arrival_distance))
                except ValueError:
                    node, edge = locate_occupancy(
                        graph, planner.nodes, x, y, tolerance_m=REAL_OCCUPANCY_TOLERANCE_M)
                execution = self._executing.get(rid)
                if execution is not None and execution[2] is not None:
                    route = row["route"]
                    index = route["segment_index"]
                    start, end = route["node_ids"][index:index + 2]
                    if node is not None:
                        if node not in (start, end):
                            raise ValueError("예상 구간 밖의 노드입니다.")
                    else:
                        # 반대 방향 edge ID도 같은 물리 통로인지 비교한다.
                        actual = occupied_resource({"occupied_node": None, "occupied_edge": edge}, graph)
                        next_edge = (edge_key(end, route["node_ids"][index + 2])
                                     if index + 2 < len(route["node_ids"]) else None)
                        if actual not in (edge_key(start, end), next_edge):
                            raise ValueError("예상 구간 밖의 통로입니다.")
                # 여러 통로에 걸쳐 점유를 확정할 수 없는 경우는 기존 정지 정책 유지.
            except (ValueError, KeyError, IndexError) as exc:
                valid = False
                self._sync_errors[rid] = f"occupancy_or_route_mismatch:{exc}"
                if previous_errors.get(rid) != self._sync_errors[rid]:
                    logging.getLogger(__name__).warning(
                        "[NAV OCCUPANCY] robot=%s actual=(%.3f, %.3f) edge=%s error=%s",
                        rid, x, y, edge, exc)
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

    def _pause(self, robot_id, reason):
        robot = self._fleet.get_robot(robot_id)
        if robot is None:
            return
        if robot.state != RobotState.EMERGENCY_STOP:
            robot.set_state(RobotState.PAUSED if robot.connected else RobotState.OFFLINE)
        logging.getLogger(__name__).warning(
            "[NAV] robot=%s state=%s reason=%s", robot_id, robot.state.value, reason)

    def stop(self, robot_id, callback=None, *, reason="request_replaced"):
        """Nav2 종료 전에는 계획/예약을 해제하지 않는다. 마지막 요청만 실행한다."""
        with self.lock:
            already_stopping = robot_id in self._stopping
            self._stopping[robot_id] = callback
            self._stop_deadlines[robot_id] = self._clock() + REAL_CANCEL_TIMEOUT_S
            self._arrivals.pop(robot_id, None)
            self._resume_pending.discard(robot_id)
            robot = self._fleet.get_robot(robot_id)
            if robot is not None and robot.connected and robot.state not in (
                    RobotState.EMERGENCY_STOP, RobotState.PAUSED):
                robot.set_state(RobotState.WAITING)
            logging.getLogger(__name__).warning(
                "[NAV cancel] robot=%s reason=%s navigation_id=%s",
                robot_id, reason, robot.navigation_id if robot else None)
            if already_stopping:
                return

            def stopped():
                with self.lock:
                    self._executing.pop(robot_id, None)
                    self._arrival_observed.pop(robot_id, None)
                    self._feedback.pop(robot_id, None)
                    self._hold.pop(robot_id, None)
                    self._lookahead_decisions.pop(robot_id, None)
                    self._stop_deadlines.pop(robot_id, None)
                    next_step = self._stopping.pop(robot_id, None)
                    if next_step is not None:
                        try:
                            next_step()
                        except (OSError, KeyError, ValueError, RuntimeError):
                            self._pause(robot_id, "after_stop_failed")
                            logging.getLogger(__name__).exception("정지 후 내비게이션 처리 실패: %s", robot_id)
            try:
                self._cancel_goal(robot_id, callback=stopped)
            except Exception:
                # 전송 실패는 정지 완료가 아니다. 예약과 취소 대기 상태를 남긴다.
                self._pause(robot_id, "cancel_send_failed")
                logging.getLogger(__name__).exception("[NAV] 취소 전송 실패: %s", robot_id)

    def cancel_after_stop(self, robot_id):
        with self.lock:
            deferred = self._deferred_requests.pop(robot_id, None)
            if deferred is not None:
                self._pause(deferred[0], "concession_interrupted")
            self._request_versions[robot_id] = self._request_versions.get(robot_id, 0) + 1
            self._arrivals.pop(robot_id, None)
            self._arrival_observed.pop(robot_id, None)
            self._feedback.pop(robot_id, None)
            self._hold.pop(robot_id, None)
            self._lookahead_decisions.pop(robot_id, None)
            self._resume_pending.discard(robot_id)
            self._cancelled.add(robot_id)
            self._requests.pop(robot_id, None)
            try:
                graph = load_route_graph()
                if self._sync(graph, DistanceAStar(graph), self._clock()):
                    self._clear_cancelled()
            except (OSError, KeyError, ValueError):
                # 그래프/점유를 확인할 수 없으면 취소된 요청의 예약도 보존한다.
                self._pause(robot_id, "cancel_cleanup_waiting_for_occupancy")
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
                raise ValueError(f"실제 로봇의 최신 위치와 점유를 확인할 수 없습니다: {self._sync_errors}")
            self._clear_cancelled()
            # request_navigation_after_stop 내부에서도 retry_waiting이 호출된다.
            # 종료되는 양보 실행이 있으면 해당 실행 종료 뒤 동일 요청을 접수한다.
            affected = self._ending_concessions(robot_id)
            if affected:
                # 양보 로봇을 Edge 중간에서 취소하지 않고 안전 Node까지 보내 둔다.
                self._deferred_requests[affected[0]] = (
                    robot_id, node_id, navigation_type, _request_version)
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
                if (rid in self._executing or rid in self._arrivals) and (
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
                robot.set_state(RobotState.MOVING if rid in self._executing
                                and rid not in self._stopping else RobotState.WAITING)

    def _replan_after_stop(self, robot_id):
        graph = load_route_graph()
        if not self._sync(graph, DistanceAStar(graph), self._clock()):
            # 최신 위치가 올 때까지 기존 예약과 점유를 유지한다.
            return
        if robot_id in self._robots and self._robots[robot_id]["route"] is not None:
            self._traffic.wait_for_reservation_after_stop(robot_id)

    def on_feedback(self, robot_id, current_waypoint):
        """Nav2 인덱스는 진행 힌트다. 점유와 노드 통과는 Pose로만 확정한다."""
        with self.lock:
            execution = self._executing.get(robot_id)
            if execution is None or not isinstance(current_waypoint, int) or current_waypoint < 0:
                return
            route = self._robots[robot_id]["route"]
            count = len(route["node_ids"]) - execution[2] - 1 if route and execution[2] is not None else 1
            if current_waypoint >= count:
                return
            if self._feedback.get(robot_id) != (execution[0], current_waypoint):
                self._feedback[robot_id] = (execution[0], current_waypoint)
                if route:
                    index = execution[2] + current_waypoint
                    logging.getLogger(__name__).info(
                        "[NAV FEEDBACK] robot=%s current_waypoint=%s segment=%s->%s",
                        robot_id, current_waypoint, route["node_ids"][index],
                        route["node_ids"][index + 1])

    def _next_segment_reason(self, rid, route, planner, graph, now):
        """다음 Edge 진입 전에 실제 점유와 이미 확정한 예약을 확인한다."""
        index = route["segment_index"]
        nodes = route["node_ids"]
        if index + 2 >= len(nodes):
            return None
        start, end = nodes[index + 1:index + 3]
        resources = (edge_key(start, end), node_key(end))
        robot = self._fleet.get_robot(rid)
        reach = now + math.dist((robot.x, robot.y), planner.nodes[start]) / self._traffic.speed_mps
        finish = reach + math.dist(planner.nodes[start], planner.nodes[end]) / self._traffic.speed_mps
        rows = self._traffic._reservations.snapshot()
        own = [row for row in rows if row.robot_id == rid
               and row.navigation_id == self._robots[rid]["navigation_id"]
               and row.segment_index == index + 1]
        if any(not any(row.resource == resource for row in own) for resource in resources):
            return "missing_reservation"
        for other in self._robots.values():
            if other["robot_id"] != rid and occupied_resource(other, graph) in resources:
                return "occupied"
        if any(row.robot_id != rid and row.resource in resources
               and row.start <= finish + self._traffic.safety_margin and row.end > reach
               for row in rows):
            return "reservation_conflict"
        return None

    def _advance_pose(self, rid, graph, planner):
        """중간 Node 도착 또는 Feedback이 뒷받침된 다음 Edge 진입을 한 번만 반영한다."""
        state = self._robots[rid]
        route = state["route"]
        execution = self._executing.get(rid)
        if route is None or execution is None or execution[2] is None:
            return
        index = route["segment_index"]
        if index >= len(route["node_ids"]) - 2:
            return  # 마지막 Node는 Action 성공과 실제 Pose를 함께 확인한다.
        target = route["node_ids"][index + 1]
        actual_node, actual_edge = state["occupied_node"], state["occupied_edge"]
        next_edge = edge_key(target, route["node_ids"][index + 2])
        feedback = self._feedback.get(rid)
        robot = self._fleet.get_robot(rid)
        at_target = (actual_node == target and
                     math.dist((robot.x, robot.y), planner.nodes[target]) <= self._arrival_distance)
        passed = (at_target or
                  (actual_edge is not None and
                   occupied_resource(state, graph) == next_edge and
                   feedback is not None and feedback[0] == execution[0] and
                   execution[2] + feedback[1] >= index + 1))
        if not passed:
            return
        self._traffic.confirm_node_arrival(rid, target)
        # 확인 직후에도 점유는 현재 Pose에 따른 값을 유지한다.
        state["occupied_node"], state["occupied_edge"] = actual_node, actual_edge
        state["current_node"] = actual_node
        if actual_edge is not None:
            self._fleet.get_robot(rid).occupied_node = None
            self._fleet.get_robot(rid).occupied_edge = actual_edge
        hold = self._hold.get(rid)
        if hold and hold[0] == target:
            if at_target:
                self.stop(rid, lambda rid=rid, node=target: self._wait_at_node(rid, node),
                          reason=hold[1])
            else:
                # Cancel 응답 전에 다음 Edge에 들어갔다면 안전 Node 정지는 보장할 수 없다.
                self._pause(rid, "hold_node_passed")
                self.stop(rid, reason="hold_node_passed")

    def _wait_at_node(self, rid, node):
        robot = self._fleet.get_robot(rid)
        graph = load_route_graph()
        planner = DistanceAStar(graph)
        try:
            if measured_distance(robot, planner.nodes[node], self._clock()) > self._arrival_distance:
                raise ValueError("hold_node_departed")
            if not self._sync(graph, planner, self._clock()) or self._robots[rid]["occupied_node"] != node:
                raise ValueError("hold_node_unconfirmed")
        except (OSError, KeyError, ValueError) as exc:
            self._pause(rid, f"hold_failed:{exc}")
            return  # 정지를 확인하지 못했으므로 예약은 유지한다.
        self._traffic.wait_for_reservation_after_stop(rid)
        self._resume_pending.add(rid)
        logging.getLogger(__name__).info("[NAV WAITING] robot=%s node=%s", rid, node)
        self._publish()

    def tick(self):
        with self.lock:
            try:
                self._tick()
            except (OSError, ValueError, KeyError, IndexError, RuntimeError):
                logging.getLogger(__name__).exception("[NAV] 주행 상태 갱신 실패")
                for rid in set(self._requests) | set(self._executing) | set(self._arrivals):
                    self._pause(rid, "navigation_update_failed")
                    if rid in self._executing and rid not in self._stopping:
                        self.stop(rid, reason="navigation_update_failed")
                    self._arrivals.pop(rid, None)

    def _tick(self):
        with self.lock:
            now = self._clock()
            for rid, deadline in list(self._stop_deadlines.items()):
                if now >= deadline:
                    self._pause(rid, "cancel_timeout")
                    self._stopping[rid] = None
                    self._stop_deadlines.pop(rid, None)
            for rid in list(self._arrivals):
                self._check_arrival(rid)
            if not self._cancelled and not self._requests and not self._traffic.has_active_requests():
                return
            graph = load_route_graph()
            planner = DistanceAStar(graph)
            now = self._clock()
            if not self._sync(graph, planner, now):
                for rid in list(self._executing):
                    if rid not in self._stopping:
                        self._pause(rid, str(self._sync_errors))
                        self.stop(rid, reason="pose_or_occupancy_invalid")
                return
            self._clear_cancelled()
            affected = self._ending_concessions()
            # 양보 Goal은 계속 감시하되, 안전 Node 도착 전에는 예약 재계획을 미룬다.
            if not self._stopping and not affected:
                self._traffic.retry_waiting(now, graph, planner)
            for rid, state in list(self._robots.items()):
                robot = self._fleet.get_robot(rid)
                if not robot.connected or robot.state in (RobotState.EMERGENCY_STOP, RobotState.PAUSED):
                    continue
                if rid in self._arrivals or rid in self._stopping or (self._stopping and rid not in self._executing):
                    continue
                if affected and rid not in self._executing:
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
                if rid in self._executing:
                    # 현재 Edge에서는 시간표 초과만으로 취소하지 않는다. 다음 Edge를 미리 본다.
                    current_resources = (
                        edge_key(route["node_ids"][route["segment_index"]], target),
                        node_key(target))
                    current_conflict = any(other["robot_id"] != rid and
                                           occupied_resource(other, graph) in current_resources
                                           for other in self._robots.values())
                    current_conflict = current_conflict or any(
                        row.robot_id != rid and row.resource in current_resources
                        and row.start <= now < row.end
                        for row in self._traffic._reservations.snapshot())
                    if current_conflict:
                        # 이미 현재 구간을 다른 로봇이 점유하면 시간표보다 충돌 방지가 우선이다.
                        self._pause(rid, "current_segment_occupied")
                        self.stop(rid, reason="current_segment_occupied")
                        continue
                    reason = self._next_segment_reason(rid, route, planner, graph, now)
                    decision = reason or "allowed"
                    if self._lookahead_decisions.get(rid) != (route["segment_index"], decision):
                        self._lookahead_decisions[rid] = (route["segment_index"], decision)
                        if route["segment_index"] + 2 < len(route["node_ids"]):
                            logging.getLogger(__name__).info(
                                "[NAV LOOKAHEAD] robot=%s current=%s->%s next=%s->%s decision=%s",
                                rid, route["node_ids"][route["segment_index"]], target,
                                target, route["node_ids"][route["segment_index"] + 2], decision)
                    if reason and rid not in self._hold:
                        self._hold[rid] = (target, reason)
                        logging.getLogger(__name__).warning(
                            "[NAV HOLD] robot=%s hold_node=%s reason=%s", rid, target, reason)
                    elif reason is None and rid in self._hold:
                        self._hold.pop(rid)
                    self._advance_pose(rid, graph, planner)
                    continue
                distance = math.dist((robot.x, robot.y), planner.nodes[target])
                arrival = now + max(0., distance - self._arrival_distance) / self._traffic.speed_mps
                permission = self._traffic.check_segment_permission(
                    rid, now=now, expected_arrival_at=arrival, graph=graph)
                if permission.decision == "replan" and permission.reason == "schedule_overrun":
                    # Real에서는 이미 지난 시간표만으로 재취소하지 않는다. 실제 점유는 위 검사에 남는다.
                    rows = self._traffic._reservations.snapshot()
                    own = {row.resource for row in rows if row.robot_id == rid
                           and row.navigation_id == state["navigation_id"]
                           and row.segment_index == route["segment_index"]}
                    resources = (edge_key(route["node_ids"][route["segment_index"]], target),
                                 node_key(target))
                    if all(resource in own for resource in resources) and not any(
                            other["robot_id"] != rid and occupied_resource(other, graph) in resources
                            for other in self._robots.values()) and not any(
                                row.robot_id != rid and row.resource in resources
                                and row.start <= arrival + self._traffic.safety_margin and row.end > now
                                for row in rows):
                        permission = type(permission)("allowed", "real_schedule_delay")
                if permission.decision == "replan":
                    self._traffic.wait_for_reservation_after_stop(rid)
                elif permission.decision == "allowed":
                    # 전송 전에 이미 알려진 다음 구간 위험을 표시해 첫 tick을 놓치지 않는다.
                    reason = self._next_segment_reason(rid, route, planner, graph, now)
                    self._send(rid, route["node_ids"][-1], route["segment_index"], planner)
                    if reason and rid in self._executing:
                        self._hold[rid] = (target, reason)
                        logging.getLogger(__name__).warning(
                            "[NAV HOLD] robot=%s hold_node=%s reason=%s", rid, target, reason)
            self._publish()

    def _send(self, rid, target, segment_index, planner):
        robot = self._fleet.get_robot(rid)
        state = self._robots[rid]
        waypoints = []
        yaw = float(robot.yaw)
        if segment_index is not None:
            route = state["route"]
            nodes = route["node_ids"]
            for index in range(segment_index + 1, len(nodes)):
                node = nodes[index]
                x, y = planner.nodes[node]
                # 중간 Node는 다음 이동 방향, 마지막 Node는 진입 방향.
                yaw = (route["waypoint_yaws"][index + 1]
                       if index + 1 < len(nodes) else route["waypoint_yaws"][index])
                waypoints.append((x, y, yaw))
            target = nodes[-1]
        else:
            x, y = planner.nodes[target]
            waypoints.append((x, y, yaw))
        final = rid in self._requests and target == self._requests[rid][0] and rid not in self._traffic._concession
        if final:
            yaw = (float(robot.yaw) if robot.navigation_type == NavigationType.RETURN
                   else self._goal_yaws.get(target, yaw))
            x, y, _ = waypoints[-1]
            waypoints[-1] = (x, y, yaw)
        if rid not in self._requests:
            self._yielding.add(rid)
        self._arrival_observed.pop(rid, None)
        self._executing[rid] = (state["navigation_id"], target, segment_index, final)
        try:
            self._send_goal(robot_id=rid, waypoints=waypoints)
            logging.getLogger(__name__).info(
                "[NAV ROUTE SEND] robot=%s route=%s waypoints=%s",
                rid, "->".join(state["route"]["node_ids"]) if state["route"] else target,
                ",".join(state["route"]["node_ids"][segment_index + 1:])
                if segment_index is not None else target)
            if rid in self._resume_pending:
                logging.getLogger(__name__).info(
                    "[NAV RESUME] robot=%s route=%s", rid,
                    "->".join(state["route"]["node_ids"]) if state["route"] else target)
                self._resume_pending.discard(rid)
        except (ValueError, RuntimeError):
            self._executing.pop(rid, None)
            self._pause(rid, "goal_send_failed")
            self.cancel_after_stop(rid)
            raise
        if rid in self._executing:
            robot.set_state(RobotState.MOVING)

    def on_execution_error(self, robot_id, reason):
        # ROS 응답 예외는 액션 종료 증거가 아니다. Goal/예약을 유지한 채 중단 표시.
        with self.lock:
            self._pause(robot_id, reason)
            if robot_id in self._stopping:
                self._stopping[robot_id] = None
            elif robot_id in self._executing:
                self.stop(robot_id, reason=reason)

    def on_result(self, robot_id, succeeded, status=None):
        """성공 결과와 최신 실제 좌표를 함께 확인한 뒤에만 후속 시퀀스 실행."""
        with self.lock:
            execution = self._executing.pop(robot_id, None)
            self._arrival_observed.pop(robot_id, None)
            if execution is None:
                return
            if execution[0] != self._robots[robot_id]["navigation_id"]:
                return
            robot = self._fleet.get_robot(robot_id)
            if (not succeeded or not robot.connected
                    or robot.state in (RobotState.EMERGENCY_STOP, RobotState.PAUSED)):
                deferred = self._deferred_requests.pop(robot_id, None)
                if deferred is not None:
                    self._pause(deferred[0], "concession_failed")
                self._pause(robot_id, f"navigation_result:{status}")
                self.cancel_after_stop(robot_id)
                return
            route = self._robots[robot_id]["route"]
            if execution[2] is not None and (route is None
                    or route["node_ids"][-1] != execution[1]
                    or route["segment_index"] != len(route["node_ids"]) - 2):
                self._pause(robot_id, "route_progress_unconfirmed")
                return  # 통과하지 못한 중간 Node를 성공으로 간주하거나 예약을 해제하지 않는다.
            self._arrivals[robot_id] = (execution, self._clock() + REAL_ARRIVAL_CONFIRM_TIMEOUT_S)
            robot.set_state(RobotState.WAITING)
            self._check_arrival(robot_id)

    def _check_arrival(self, robot_id):
        execution, deadline = self._arrivals[robot_id]
        navigation_id, target, segment_index, final = execution
        state = self._robots[robot_id]
        robot = self._fleet.get_robot(robot_id)
        if navigation_id != state["navigation_id"]:
            self._arrivals.pop(robot_id, None)
            return
        if not robot.connected or robot.state in (RobotState.EMERGENCY_STOP, RobotState.PAUSED):
            self._arrivals.pop(robot_id, None)
            self._pause(robot_id, "arrival_interrupted")
            self.cancel_after_stop(robot_id)
            return
        now = self._clock()
        distance = None
        try:
            planner = DistanceAStar(load_route_graph())
            target_position = planner.nodes[target]
            distance = measured_distance(robot, target_position, now)
            reason = "arrival_outside_tolerance" if distance > self._arrival_distance else None
        except (OSError, ValueError, KeyError) as exc:
            reason = str(exc)
        if reason is not None:
            if now < deadline:
                return
            self._arrivals.pop(robot_id, None)
            self._pause(robot_id, f"arrival_failed:{reason}, target={target}, distance={distance}")
            self.cancel_after_stop(robot_id)
            return
        self._arrivals.pop(robot_id, None)
        logging.getLogger(__name__).info(
            "[NAV arrival] robot=%s target=%s actual=(%.3f, %.3f) goal=(%.3f, %.3f) distance=%.3f tolerance=%.3f",
            robot_id, target, robot.x, robot.y, *target_position, distance, self._arrival_distance)
        # 도착 검증에는 위의 원본 좌표만 사용한다. 계획용 좌표 보정은 검증 뒤 수행.
        state["x"], state["y"] = target_position
        state["current_node"] = state["occupied_node"] = target
        state["occupied_edge"] = None
        if segment_index is not None:
            self._traffic.confirm_node_arrival(robot_id, target)
        robot.current_node = robot.occupied_node = target
        robot.occupied_edge = None
        if final:
            robot.next_node = robot.next_edge = None
            self._requests.pop(robot_id, None)
            self._on_complete(robot_id)
        elif state["route"] is None and robot_id not in self._traffic._concession:
            robot.route = None
            robot.set_state(RobotState.IDLE)
        self._publish()
        deferred = self._deferred_requests.pop(robot_id, None)
        if deferred is not None:
            priority, node, navigation_type, version = deferred
            self.request(priority, node, navigation_type, _request_version=version)
