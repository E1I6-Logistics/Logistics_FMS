from __future__ import annotations

import json
import logging
from threading import RLock
from time import monotonic
from urllib.request import urlopen
from typing import Any

from ..config import ZENOH_STALE_GRACE_SECONDS

ZENOH_REST_BASE = "http://127.0.0.1:8001"
logger = logging.getLogger("fms.zenoh")


class ZenohConnectionManager:
    def __init__(self) -> None:
        self._lock = RLock()
        self._known_devices: dict[str, dict[str, Any]] = {}
        self._last_seen: dict[str, float] = {}
        self._last_success_at: float | None = None
        self._consecutive_failures = 0

    def _get_json(self, path: str) -> list[dict[str, Any]]:
        started = monotonic()
        try:
            with urlopen(
                f"{ZENOH_REST_BASE}{path}",
                timeout=2.0,
            ) as response:
                result = json.load(response)
        except Exception:
            logger.exception(
                "event=zenoh_rest_failed path=%s duration_ms=%.1f",
                path,
                (monotonic() - started) * 1000,
            )
            raise

        duration_ms = (monotonic() - started) * 1000
        if duration_ms >= 1000:
            logger.warning(
                "event=zenoh_rest_slow path=%s duration_ms=%.1f",
                path,
                duration_ms,
            )
        return result

    def _get_sessions(self) -> dict[str, str]:
        data = self._get_json("/@/local/router")

        if not data:
            return {}

        sessions = data[0].get("value", {}).get("sessions", [])

        result: dict[str, str] = {}

        for session in sessions:
            zid = session.get("peer")

            if not zid:
                continue

            links = session.get("links", [])

            if not links:
                continue

            dst = links[0].get("dst", "")

            if not dst.startswith("tcp/"):
                continue

            address = dst.removeprefix("tcp/")
            ip = address.rsplit(":", 1)[0]

            result[zid] = ip

        return result

    def _get_robot_routes(self) -> dict[str, str]:
        routes = self._get_json("/@/*/ros2/route/**")

        result: dict[str, str] = {}

        for route in routes:
            key = str(route.get("key", ""))

            # @/<ZID>/ros2/route/...
            parts = key.split("/")

            if len(parts) < 7:
                continue

            zid = parts[1]

            try:
                route_index = parts.index("route")
            except ValueError:
                continue

            # route/topic/pub/robot2/imu
            # route/service/srv/robot2/...
            if len(parts) <= route_index + 3:
                continue

            robot_id = parts[route_index + 3]

            if robot_id.startswith("robot"):
                result[zid] = robot_id

        return result

    def connections(self) -> list[dict[str, Any]]:
        now = monotonic()
        try:
            sessions = self._get_sessions()
            robot_routes = self._get_robot_routes()
        except Exception as exc:
            with self._lock:
                self._consecutive_failures += 1
                logger.warning(
                    "event=zenoh_snapshot_unavailable consecutive_failures=%s "
                    "known_robots=%s error=%r",
                    self._consecutive_failures,
                    len(self._known_devices),
                    exc,
                )
                return self._unavailable_snapshot()

        connected: dict[str, dict[str, Any]] = {}

        for zid, robot_id in robot_routes.items():

            ip = sessions.get(zid)

            if ip is None:
                continue

            # FMS 자신의 Local Zenoh Bridge 제외
            if ip in {"127.0.0.1", "::1"}:
                continue

            connected[robot_id] = {
                "ip": ip,
                "name": robot_id,
                "known": True,
                "connected": True,
                "blocked": False,
                "state": "CONNECTED",
                "zid": zid,
            }

        with self._lock:
            previous_connected = {
                robot_id
                for robot_id, device in self._known_devices.items()
                if device.get("connected")
            }
            current_connected = set(connected)

            for robot_id, device in connected.items():
                self._known_devices[robot_id] = device
                self._last_seen[robot_id] = now

            # Preserve known robots in API responses so a transient discovery
            # gap does not make UI rows disappear. They are deliberately marked
            # disconnected, so commands remain blocked until Zenoh confirms them.
            for robot_id, device in list(self._known_devices.items()):
                if robot_id in current_connected:
                    continue
                last_seen = self._last_seen.get(robot_id)
                age = None if last_seen is None else now - last_seen
                retained = dict(device)
                retained["connected"] = False
                retained["state"] = (
                    "DEGRADED"
                    if age is not None and age <= ZENOH_STALE_GRACE_SECONDS
                    else "OFFLINE"
                )
                self._known_devices[robot_id] = retained

            self._last_success_at = now
            self._consecutive_failures = 0

            newly_connected = current_connected - previous_connected
            newly_disconnected = previous_connected - current_connected
            if newly_connected:
                logger.info(
                    "event=zenoh_robots_connected robots=%s session_count=%s "
                    "route_robot_count=%s",
                    sorted(newly_connected),
                    len(sessions),
                    len(robot_routes),
                )
            if newly_disconnected:
                logger.warning(
                    "event=zenoh_robots_disconnected robots=%s "
                    "session_count=%s route_robot_count=%s",
                    sorted(newly_disconnected),
                    len(sessions),
                    len(robot_routes),
                )

            return sorted(
                (dict(device) for device in self._known_devices.values()),
                key=lambda device: device["name"],
            )

    def _unavailable_snapshot(self) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        for robot_id, device in list(self._known_devices.items()):
            retained = dict(device)
            retained["connected"] = False
            retained["state"] = "DEGRADED"
            self._known_devices[robot_id] = retained
            result.append(retained)
        return sorted(result, key=lambda device: device["name"])


zenoh_connection_manager = ZenohConnectionManager()
