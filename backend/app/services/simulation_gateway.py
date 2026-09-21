from __future__ import annotations

import asyncio
import math
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from ..config import (
    CMD_VEL_MAX_ANGULAR,
    CMD_VEL_MAX_LINEAR,
    ROBOT_COUNT,
)
from ..schemas.robot import normalize_robot_id, to_ui_robot_id
from .map_service import world_to_pixel
from .route_graph import get_node, list_nodes
from .route_planner import plan_route

logger = logging.getLogger(__name__)


@dataclass
class _SimRobot:
    robot_id: str
    x: float
    y: float
    yaw: float = 0.0
    battery: float = 100.0
    status: str = "IDLE"
    linear_x: float = 0.0
    angular_z: float = 0.0
    target_x: float | None = None
    target_y: float | None = None
    current_node: str | None = None
    transit_node: str | None = None
    transit_edge: str | None = None
    route_nodes: list[str] = field(default_factory=list)
    route_edges: list[str] = field(default_factory=list)
    waypoints: list[tuple[float, float]] = field(default_factory=list)
    route_index: int = 1
    route_delay: float = 0.0


class SimulationGateway:
    def __init__(self) -> None:
        self._robots: dict[str, _SimRobot] = {}
        self._task: asyncio.Task[None] | None = None
        self._started = False

    @property
    def active(self) -> bool:
        return self._started and self._task is not None and not self._task.done()

    def start(self) -> None:
        if self._started:
            return
        # robot1 -> N0, robot2 -> N1, robot3 -> N2
        initial_nodes = (0, 1, 2)
        self._robots = {}
        for index in range(1, ROBOT_COUNT + 1):
            robot_id = f"robot{index}"
            node = get_node(initial_nodes[(index - 1) % len(initial_nodes)])
            self._robots[robot_id] = _SimRobot(
                robot_id=robot_id,
                x=node["x"],
                y=node["y"],
                current_node=str(node["id"]),
            )
        self._started = True
        self._task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        self._started = False
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    def status_snapshot(self) -> dict[str, Any]:
        return {
            "active": self.active,
            "mode": "simulation",
            "robots": list(self._robots),
        }

    def _get_robot(self, robot_id: str) -> _SimRobot:
        backend_id = normalize_robot_id(robot_id)
        robot = self._robots.get(backend_id)
        if robot is None:
            raise ValueError(f"Unknown robot: {backend_id}")
        return robot

    def _response(self, robot: _SimRobot, message: str) -> dict[str, Any]:
        return {
            "status": "SUCCESS",
            "robot_id": robot.robot_id,
            "ui_id": to_ui_robot_id(robot.robot_id),
            "topic": f"simulation://{robot.robot_id}",
            "message": message,
            "mode": "simulation",
        }

    def send_cmd_vel(
        self,
        robot_id: str,
        linear_x: float,
        angular_z: float,
    ) -> dict[str, Any]:
        robot = self._get_robot(robot_id)
        # Idle manual-control heartbeats must not cancel autonomous navigation.
        if not linear_x and not angular_z and (robot.route_nodes or robot.target_x is not None):
            return self._response(robot, "자율 이동 유지")
        robot.target_x = None
        robot.target_y = None
        self._clear_route(robot)
        if linear_x or angular_z:
            robot.current_node = None
            robot.transit_node = None
            robot.transit_edge = None
        robot.linear_x = max(-CMD_VEL_MAX_LINEAR, min(CMD_VEL_MAX_LINEAR, float(linear_x)))
        robot.angular_z = max(-CMD_VEL_MAX_ANGULAR, min(CMD_VEL_MAX_ANGULAR, float(angular_z)))
        robot.status = "MOVING" if robot.linear_x or robot.angular_z else "IDLE"
        return self._response(robot, "시뮬레이션 cmd_vel 적용 완료")

    def stop_robot(self, robot_id: str) -> dict[str, Any]:
        robot = self._get_robot(robot_id)
        self._clear_route(robot)
        robot.target_x = robot.target_y = None
        return self.send_cmd_vel(robot_id, 0.0, 0.0)

    def navigate_to_pose(
        self,
        robot_id: str,
        x: float,
        y: float,
        frame_id: str = "map",
    ) -> dict[str, Any]:
        if frame_id != "map":
            raise ValueError(f"지원하지 않는 simulation frame: {frame_id}")
        robot = self._get_robot(robot_id)
        self._clear_route(robot)
        robot.current_node = None
        robot.transit_node = None
        robot.transit_edge = None
        robot.linear_x = 0.0
        robot.angular_z = 0.0
        robot.target_x = float(x)
        robot.target_y = float(y)
        robot.status = "NAVIGATING"
        result = self._response(robot, "시뮬레이션 목표 적용 완료")
        result.update({"x": robot.target_x, "y": robot.target_y, "frame_id": frame_id})
        return result

    @staticmethod
    def _clear_route(robot: _SimRobot) -> None:
        robot.route_nodes = []
        robot.route_edges = []
        robot.waypoints = []
        robot.route_index = 1
        robot.route_delay = 0.0

    def navigate_to_node(self, robot_id: str, node_id: str | int) -> dict[str, Any]:
        robot = self._get_robot(robot_id)
        start = robot.transit_node or robot.current_node
        if start is None:
            nearest = min(list_nodes(), key=lambda node: math.hypot(node["x"] - robot.x, node["y"] - robot.y))
            if math.hypot(nearest["x"] - robot.x, nearest["y"] - robot.y) > 0.03:
                raise ValueError("로봇이 경로 밖에 있습니다. 노드 좌표로 복귀한 후 노드 이동을 실행하세요.")
            start = str(nearest["id"])
        # Plan before mutating state: an unreachable goal must not cancel a valid route.
        route = plan_route(start, str(node_id))
        if robot.transit_node is not None:
            route["node_ids"].insert(0, robot.current_node)
            route["edge_ids"].insert(0, robot.transit_edge)
            node = get_node(robot.current_node)
            route["waypoints"].insert(0, (node["x"], node["y"]))
        robot.target_x = robot.target_y = None
        robot.linear_x = robot.angular_z = 0.0
        robot.route_nodes = route["node_ids"]
        robot.route_edges = route["edge_ids"]
        robot.waypoints = route["waypoints"]
        robot.route_index = 1
        robot.current_node = robot.route_nodes[0]
        if len(robot.route_nodes) > 1:
            robot.transit_node = robot.route_nodes[1]
            robot.transit_edge = robot.route_edges[0]
            robot.status = "ROUTE_READY"
            # Publish the full route before the first movement tick.
            robot.route_delay = 0.3
        else:
            self._clear_route(robot)
            robot.status = "IDLE"
        result = self._response(robot, "경로 생성 완료")
        result["route"] = self.robot_snapshot(robot.robot_id)["route"]
        return result

    def robot_snapshot(self, robot_id: str) -> dict[str, Any]:
        robot = self._get_robot(robot_id)
        pixel_x, pixel_y = world_to_pixel(robot.x, robot.y)
        return {
            "robot_id": robot.robot_id,
            "ui_id": to_ui_robot_id(robot.robot_id),
            "x": robot.x, "y": robot.y, "yaw": robot.yaw,
            "battery": round(robot.battery, 1), "status": robot.status,
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "mode": "simulation", "source": "simulation",
            "pixel_x": pixel_x,
            "pixel_y": pixel_y,
            "map_pose_received": True,
            "pose_source": "SIMULATION",
            "connection_state": "ONLINE",
            "route": {
                "node_ids": list(robot.route_nodes),
                "edge_ids": list(robot.route_edges),
                "phase": "ready" if robot.status == "ROUTE_READY" else "moving",
                "segment_index": max(0, robot.route_index - 1),
            } if robot.route_nodes else None,
        }

    def robot_snapshots(self) -> list[dict[str, Any]]:
        return [self.robot_snapshot(key) for key in self._robots]

    async def _run(self) -> None:
        loop = asyncio.get_running_loop()
        last = loop.time()
        while self._started:
            await asyncio.sleep(0.1)
            now = loop.time()
            dt = min(now - last, 0.25)
            last = now
            for robot in self._robots.values():
                self._advance(robot, dt)
                try:
                    await self._publish(robot)
                except Exception:
                    logger.exception("Simulation telemetry failed for %s", robot.robot_id)

    @staticmethod
    def _advance(robot: _SimRobot, dt: float) -> None:
        if robot.route_nodes:
            if robot.route_delay > 0:
                robot.route_delay = max(0.0, robot.route_delay - dt)
                return
            robot.status = "NAVIGATING"
            remaining = 0.25 * dt
            while robot.route_index < len(robot.waypoints):
                target_x, target_y = robot.waypoints[robot.route_index]
                dx, dy = target_x - robot.x, target_y - robot.y
                distance = math.hypot(dx, dy)
                if distance > 0:
                    robot.yaw = math.atan2(dy, dx)
                if distance > remaining:
                    robot.x += dx / distance * remaining
                    robot.y += dy / distance * remaining
                    return
                robot.x, robot.y = target_x, target_y
                remaining -= distance
                robot.current_node = robot.route_nodes[robot.route_index]
                robot.route_index += 1
                if robot.route_index < len(robot.route_nodes):
                    robot.transit_node = robot.route_nodes[robot.route_index]
                    robot.transit_edge = robot.route_edges[robot.route_index - 1]
            robot.transit_node = robot.transit_edge = None
            SimulationGateway._clear_route(robot)
            robot.status = "IDLE"
            return
        if robot.target_x is not None and robot.target_y is not None:
            dx = robot.target_x - robot.x
            dy = robot.target_y - robot.y
            distance = math.hypot(dx, dy)
            if distance <= 0.03:
                robot.x = robot.target_x
                robot.y = robot.target_y
                robot.target_x = None
                robot.target_y = None
                robot.status = "IDLE"
                return
            speed = 0.25
            step = min(distance, speed * dt)
            robot.x += dx / distance * step
            robot.y += dy / distance * step
            robot.yaw = math.atan2(dy, dx)
            return

        if robot.linear_x or robot.angular_z:
            robot.yaw += robot.angular_z * dt
            robot.x += math.cos(robot.yaw) * robot.linear_x * dt
            robot.y += math.sin(robot.yaw) * robot.linear_x * dt

    async def _publish(self, robot: _SimRobot) -> None:
        robot.battery = max(0.0, robot.battery - 0.001)
        from .zenoh_service import publish_telemetry

        await publish_telemetry(self.robot_snapshot(robot.robot_id))


simulation_gateway = SimulationGateway()
