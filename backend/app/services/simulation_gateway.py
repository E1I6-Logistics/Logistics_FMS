from __future__ import annotations

import asyncio
import math
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from ..config import (
    CMD_VEL_MAX_ANGULAR,
    CMD_VEL_MAX_LINEAR,
    ZENOH_ROBOT_COUNT,
)
from ..database.database import upsert_robot_state
from ..schemas.robot import normalize_robot_id, to_ui_robot_id
from .route_graph import get_node


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


class SimulationGateway:
    def __init__(self) -> None:
        self._robots: dict[str, _SimRobot] = {}
        self._task: asyncio.Task[None] | None = None
        self._started = False

    @property
    def active(self) -> bool:
        return self._started

    def start(self) -> None:
        if self._started:
            return
        initial_nodes = (2, 0, 1)
        self._robots = {}
        for index in range(1, ZENOH_ROBOT_COUNT + 1):
            robot_id = f"robot{index}"
            node = get_node(initial_nodes[(index - 1) % len(initial_nodes)])
            self._robots[robot_id] = _SimRobot(
                robot_id=robot_id,
                x=node["x"],
                y=node["y"],
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
        robot.target_x = None
        robot.target_y = None
        robot.linear_x = max(-CMD_VEL_MAX_LINEAR, min(CMD_VEL_MAX_LINEAR, float(linear_x)))
        robot.angular_z = max(-CMD_VEL_MAX_ANGULAR, min(CMD_VEL_MAX_ANGULAR, float(angular_z)))
        robot.status = "MOVING" if robot.linear_x or robot.angular_z else "IDLE"
        return self._response(robot, "시뮬레이션 cmd_vel 적용 완료")

    def stop_robot(self, robot_id: str) -> dict[str, Any]:
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
        robot.linear_x = 0.0
        robot.angular_z = 0.0
        robot.target_x = float(x)
        robot.target_y = float(y)
        robot.status = "NAVIGATING"
        result = self._response(robot, "시뮬레이션 목표 적용 완료")
        result.update({"x": robot.target_x, "y": robot.target_y, "frame_id": frame_id})
        return result

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
                await self._publish(robot)

    @staticmethod
    def _advance(robot: _SimRobot, dt: float) -> None:
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

        await publish_telemetry(
            {
                "robot_id": robot.robot_id,
                "ui_id": to_ui_robot_id(robot.robot_id),
                "x": round(robot.x, 3),
                "y": round(robot.y, 3),
                "yaw": round(robot.yaw, 3),
                "battery": round(robot.battery, 1),
                "status": robot.status,
                "updated_at": datetime.now(timezone.utc).isoformat(),
                "source": "simulation",
            }
        )


simulation_gateway = SimulationGateway()
