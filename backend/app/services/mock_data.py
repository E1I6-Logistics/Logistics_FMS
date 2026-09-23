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
from .route_graph import get_node


_MOCK_ROBOT_DEFINITIONS = {
    "robot1": {"node_id": "0", "status": "WORKING", "battery": 92.0},
    "robot2": {"node_id": "1", "status": "IDLE", "battery": 78.0},
    "robot3": {"node_id": "2", "status": "IDLE", "battery": 64.0},
}

_MOCK_CONNECTIONS = {
    "10.10.141.220": "robot1",
    "10.10.141.221": "robot2",
    "10.10.141.222": "robot3",
}


class MockFmsStore:
    """Volatile state used only to keep the frontend contract operational."""

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

    def robot_snapshots(self, mode: str) -> list[dict[str, Any]]:
        with self._lock:
            return [self._snapshot(robot, mode) for robot in self._robots.values()]

    def robot_snapshot(self, robot_id: str, mode: str) -> dict[str, Any]:
        with self._lock:
            return self._snapshot(self._get_robot(robot_id), mode)

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

    @staticmethod
    def _command_response(
        robot_id: str,
        command: str,
        target: dict[str, Any] | None,
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
        target = get_node(node_id)
        with self._lock:
            robot = self._get_robot(robot_id)
            start_node = robot.get("current_node")
            node_ids = [str(target["id"])]
            if start_node is not None and str(start_node) != str(target["id"]):
                node_ids.insert(0, str(start_node))
            robot["status"] = "NAVIGATING"
            robot["route"] = {
                "node_ids": node_ids,
                "edge_ids": [],
                "phase": "ready",
                "segment_index": 0,
            }
        result = self._command_response(
            robot_id,
            "goal-node",
            {"node_id": target["id"], "x": target["x"], "y": target["y"]},
        )
        result["route"] = deepcopy(robot["route"])
        result["node"] = target
        return result

    def navigate_to_pose(self, robot_id: str, x: float, y: float) -> dict[str, Any]:
        """TODO: Replace with user-defined coordinate movement control."""
        with self._lock:
            robot = self._get_robot(robot_id)
            robot.update(
                {
                    "x": float(x),
                    "y": float(y),
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


mock_fms = MockFmsStore()
