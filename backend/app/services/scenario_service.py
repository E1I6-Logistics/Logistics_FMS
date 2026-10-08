"""단일 시나리오 실행 관리. ROS/Mock 의존성은 해당 모드에서만 로드한다."""
import asyncio
from copy import deepcopy
from functools import wraps
import json
import math
from threading import RLock
from time import monotonic
from uuid import uuid4

from ..config import BASE_DIR, REAL_OCCUPANCY_TOLERANCE_M, REAL_POSE_TIMEOUT_S
from ..schemas.robot import normalize_robot_id
from .command_service import navigate_to_node, stop_robot
from .mode_service import mode_manager
from .pathfinding import DistanceAStar
from .route_graph import load_route_graph, locate_current_node

SCENARIO_PATH = BASE_DIR / "tests/traffic_scenarios.json"


def load_config():
    try:
        config = json.loads(SCENARIO_PATH.read_text(encoding="utf-8"))
        names = set()
        for scenario in config["scenarios"]:
            name = scenario["name"]
            if not isinstance(name, str) or not name or name in names:
                raise ValueError("시나리오 이름이 비어 있거나 중복되었습니다.")
            names.add(name)
            if not isinstance(scenario["description"], str):
                raise ValueError("description은 문자열이어야 합니다.")
            ids, starts = set(), set()
            for robot in scenario["robots"]:
                robot["id"] = normalize_robot_id(robot["id"])
                robot["start"] = str(robot["start"])
                if robot["goal"] is not None:
                    robot["goal"] = str(robot["goal"])
                if robot["id"] in ids or robot["start"] in starts:
                    raise ValueError(f"{name}: 로봇 또는 시작 노드 중복")
                ids.add(robot["id"])
                starts.add(robot["start"])
            if not ids or not any(r["goal"] is not None for r in scenario["robots"]):
                raise ValueError(f"{name}: 이동 대상이 필요합니다.")
        for mode in ("simulation", "real"):
            timeout = float(config["timeout_seconds"][mode])
            if not math.isfinite(timeout) or timeout <= 0:
                raise ValueError("제한 시간은 유한한 양수여야 합니다.")
        return config
    except (KeyError, TypeError, OSError) as exc:
        raise ValueError(f"시나리오 설정 오류: {exc}") from exc


def robot_states(mode):
    if mode == "simulation":
        from .mock_data import mock_fms
        states = mock_fms.robot_snapshots(mode)
        connections = {r["name"]: r["connected"] for r in mock_fms.connections()}
        return {r["robot_id"]: dict(r, connected=connections.get(r["robot_id"], False),
                                   fresh=True, active=r["goal_node"] is not None or r["route"] is not None)
                for r in states}
    from .fleet_manager import fleet_manager
    from ..ros2.ros_gateway import ros_gateway
    result = {}
    for robot in fleet_manager.get_all_robots():
        pending = ros_gateway.navigation_active(robot.robot_id)
        with robot._lock:
            received = robot.pose_received_at
            result[robot.robot_id] = dict(
                robot_id=robot.robot_id, status=robot.state.value, x=robot.x, y=robot.y,
                current_node=robot.current_node, goal_node=robot.goal_node,
                route=deepcopy(robot.route), connected=robot.connected,
                fresh=received is not None and 0 <= monotonic() - received <= REAL_POSE_TIMEOUT_S,
                active=pending or robot.navigation_type is not None,
                order_id=robot.order_id,
            )
    return result


class ScenarioManager:
    def __init__(self):
        self.lock = RLock()
        self._task = None
        self._status = {"state": "idle", "name": None, "run_id": None, "robots": [], "message": ""}

    @property
    def active(self):
        return self._status["state"] in ("running", "stopping")

    def status(self):
        with self.lock:
            return deepcopy(self._status)

    def ensure_available(self, robot_id=None):
        with self.lock:
            if self.active and (robot_id is None or normalize_robot_id(robot_id) in self._status["robot_ids"]):
                raise ValueError("시나리오 실행 중입니다. 완료 또는 정지 후 다시 시도하세요.")

    def protect_command(self, method):
        @wraps(method)
        def guarded(owner, robot_id, *args, **kwargs):
            with self.lock:
                self.ensure_available(robot_id)
                return method(owner, robot_id, *args, **kwargs)
        return guarded

    def start(self, name):
        with self.lock:
            self.ensure_available()
            config = load_config()
            scenario = next((s for s in config["scenarios"] if s["name"] == name), None)
            if scenario is None:
                raise ValueError(f"알 수 없는 시나리오: {name}")
            mode = mode_manager.mode
            graph = load_route_graph()
            expected = json.loads((BASE_DIR / "routes/test.geojson").read_text())
            if graph != expected:
                raise ValueError("서버 그래프가 routes/test.geojson과 다릅니다.")
            planner = DistanceAStar(graph)
            states = robot_states(mode)
            specs = scenario["robots"]
            errors = []
            # 추가 로봇의 양보/주문 주행이 테스트에 섞이지 않도록 기존 전체 Fleet 계약 유지.
            configured = {r["id"] for r in specs}
            extra = {rid for rid, r in states.items() if r["connected"]} - configured
            if extra:
                errors.append(f"JSON에 없는 연결 로봇: {', '.join(sorted(extra))}")
            for spec in specs:
                rid, start, goal = spec["id"], spec["start"], spec["goal"]
                if start not in planner.nodes or (goal is not None and goal not in planner.nodes):
                    errors.append(f"{rid}: 존재하지 않는 시작/목적지 노드")
                    continue
                if goal is not None:
                    try:
                        planner.plan(start, goal)
                    except ValueError:
                        errors.append(f"{rid}: {start} → {goal} 연결 경로 없음")
                row = states.get(rid)
                if row is None or not row["connected"]:
                    errors.append(f"{rid}: 연결되지 않음 (필요 시작점 N{start})")
                    continue
                if not row["fresh"] or any(v is None or not math.isfinite(v) for v in (row["x"], row["y"])):
                    errors.append(f"{rid}: 최신 위치 없음 (필요 시작점 N{start})")
                    continue
                if row["status"] != "IDLE" or row["active"] or row.get("order_id"):
                    errors.append(f"{rid}: 작업 가능 상태가 아님 ({row['status']})")
                if mode == "real":
                    node = locate_current_node(planner.nodes, row["x"], row["y"], REAL_OCCUPANCY_TOLERANCE_M)
                    if node != start:
                        distance = math.dist((row["x"], row["y"]), planner.nodes[start])
                        errors.append(f"{rid}: 시작 위치 불일치 — N{start}까지 {distance:.3f}m "
                                      f"(허용 {REAL_OCCUPANCY_TOLERANCE_M:.3f}m)")
            if errors:
                raise ValueError("실행 거부:\n" + "\n".join(errors))
            self._status = dict(state="running", run_id=uuid4().hex, name=name,
                                description=scenario["description"], mode=mode,
                                robot_ids=[r["id"] for r in specs], robots=[],
                                elapsed=0., message="시작 위치 준비 및 명령 전송 중")
            self._task = asyncio.create_task(self._run(scenario, graph, planner.nodes,
                                                      float(config["timeout_seconds"][mode])))
            return self.status()

    async def _run(self, scenario, graph, nodes, timeout):
        mode = self._status["mode"]
        specs = scenario["robots"]
        goals = {r["id"]: r["goal"] for r in specs if r["goal"] is not None}
        started = monotonic()
        touched = False
        try:
            if self._status["state"] == "stopping":
                raise ValueError(self._status["message"])
            if mode == "simulation":
                from simulation.scenarios import prepare
                touched = True
                prepare(specs, nodes)
            for rid, goal in goals.items():
                if mode_manager.mode != mode:
                    raise ValueError("운용 모드가 변경되었습니다.")
                touched = True
                navigate_to_node(rid, goal, mode)
            self._status["message"] = "주행 및 도착 후 동작 완료 대기 중"
            while True:
                if self._status["state"] == "stopping":
                    raise ValueError(self._status["message"])
                if mode_manager.mode != mode or load_route_graph() != graph:
                    raise ValueError("실행 중 운용 모드 또는 그래프가 변경되었습니다.")
                states = robot_states(mode)
                rows = []
                for spec in specs:
                    rid = spec["id"]
                    row = states.get(rid)
                    if row is None or not row["connected"] or not row["fresh"]:
                        raise ValueError(f"{rid}: 연결 또는 최신 위치 확인 실패")
                    if row["status"] in ("PAUSED", "EMERGENCY_STOP", "OFFLINE"):
                        raise ValueError(f"{rid}: {row['status']}")
                    rows.append(dict(robot_id=rid, status=row["status"],
                                     current_node=row["current_node"], goal=spec["goal"]))
                self._status.update(robots=rows, elapsed=round(monotonic() - started, 2))
                done = all(states[rid]["status"] == "IDLE" and not states[rid]["active"]
                           and states[rid]["route"] is None
                           and str(states[rid]["current_node"]) == goal for rid, goal in goals.items())
                # 양보 중인 비이동 대상도 종료되어야 다음 테스트와 충돌하지 않는다.
                done &= all(row["status"] == "IDLE" and not states[row["robot_id"]]["active"] for row in rows)
                if done:
                    self._status.update(state="completed", message="모든 로봇의 주행 및 후속 동작 완료")
                    return
                if monotonic() - started >= timeout:
                    raise ValueError(f"{timeout:g}초 내 미완료 (교착 확정 아님)")
                await asyncio.sleep(.1)
        except (Exception, asyncio.CancelledError) as exc:
            reason = str(exc) or "서버 종료로 중단"
            self._status.update(state="stopping", message=reason)
            errors = []
            if touched:
                for spec in specs:
                    try:
                        stop_robot(spec["id"], mode)
                    except Exception as stop_error:
                        errors.append(f"{spec['id']} 정지 요청 실패: {stop_error}")
            self._status.update(state="failed", message="\n".join([reason, *errors]))

    def interrupt(self, robot_id=None):
        with self.lock:
            if self.active and (robot_id is None or normalize_robot_id(robot_id) in self._status["robot_ids"]):
                self._status.update(state="stopping", message="정지 요청으로 시나리오 중단")

    async def shutdown(self):
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                # 실행 coroutine이 시작하기 전에 취소되면 전송한 명령이 없다.
                self._status.update(state="failed", message="실행 시작 전 서버 종료")


scenario_manager = ScenarioManager()
