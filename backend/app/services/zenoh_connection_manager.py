from __future__ import annotations

import json
from urllib.request import urlopen
from typing import Any

ZENOH_REST_BASE = "http://127.0.0.1:8001"


class ZenohConnectionManager:

    def _get_json(self, path: str) -> list[dict[str, Any]]:
        with urlopen(
            f"{ZENOH_REST_BASE}{path}",
            timeout=2.0,
        ) as response:
            return json.load(response)

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
        try:
            sessions = self._get_sessions()
            robot_routes = self._get_robot_routes()
        except Exception:
            sessions = {}
            robot_routes = {}

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

        return sorted(connected.values(), key=lambda device: device["name"])


zenoh_connection_manager = ZenohConnectionManager()
