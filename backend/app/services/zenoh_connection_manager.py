from __future__ import annotations

import json
from time import strftime
from urllib.request import urlopen
from typing import Any

ZENOH_REST_BASE = "http://127.0.0.1:8001"


class ZenohConnectionManager:

    def __init__(self):
        self._last_successful: list[dict[str, Any]] = []

    def last_successful(self) -> list[dict[str, Any]]:
        devices = []
        for device in self._last_successful:
            devices.append(device.copy())
        return devices

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
        except Exception as exc:
            print(f"[{strftime('%Y-%m-%d %H:%M:%S')}] [ERROR] [ZENOH CONNECTIONS ERROR] "
                  f"REST 연결 목록 조회 실패 error_type={type(exc).__name__} detail={exc!r}; "
                  "기존 로봇 연결 상태 유지", flush=True)
            # 조회 자체가 실패했다. 이 결과로 로봇을 연결 해제하면 안 된다.
            raise ConnectionError("Zenoh 연결 목록 조회 실패") from exc

        connected: dict[str, dict[str, Any]] = {}

        for zid, robot_id in robot_routes.items():

            ip = sessions.get(zid)

            if ip is None:
                continue

            # 같은 컴퓨터에서 실행 중인 FMS의 Zenoh 연결은 로봇이 아니다.
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

        devices = sorted(connected.values(), key=lambda device: device["name"])
        self._last_successful = [device.copy() for device in devices]
        return devices


zenoh_connection_manager = ZenohConnectionManager()
