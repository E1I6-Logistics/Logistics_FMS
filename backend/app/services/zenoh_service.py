from __future__ import annotations

import asyncio
import json
import re
import logging

from typing import (
    Any,
    Optional,
)

import zenoh

from fastapi import WebSocket

from ..config import (
    ZENOH_ENDPOINT,
)
from .mode_service import mode_manager

# from ..database.database import (
#     upsert_robot_state,
# )

from ..schemas.robot import (
    normalize_robot_id,
    to_ui_robot_id,
)

# ============================================================
# Dashboard WebSocket Manager
# ============================================================


class ConnectionManager:

    def __init__(
        self,
    ) -> None:

        self.active_connections: list[WebSocket] = []

    async def connect(
        self,
        websocket: WebSocket,
    ) -> None:

        await websocket.accept()

        self.active_connections.append(websocket)

    def disconnect(
        self,
        websocket: WebSocket,
    ) -> None:

        if websocket in self.active_connections:

            self.active_connections.remove(websocket)

    async def broadcast(
        self,
        message: dict[str, Any],
    ) -> None:

        dead: list[WebSocket] = []

        for connection in self.active_connections:

            try:

                await connection.send_json(message)

            except Exception:

                dead.append(connection)

        for connection in dead:

            self.disconnect(connection)


manager = ConnectionManager()


# ============================================================
# Zenoh Runtime
# ============================================================

_session = None

_subscriber = None

_loop: Optional[asyncio.AbstractEventLoop] = None


# ============================================================
# 상태
# ============================================================


def is_ready() -> bool:

    return _session is not None


def status_snapshot() -> dict[str, Any]:

    return {
        "connected": is_ready(),
        "endpoint": ZENOH_ENDPOINT,
        "dashboard_clients": len(manager.active_connections),
        "role": "fms_native_data",
        "subscriptions": [
            "**/telemetry",
        ],
    }


# ============================================================
# Telemetry Payload Parsing
# ============================================================


def _extract_json(
    payload: bytes,
) -> Optional[dict[str, Any]]:
    """
    Native JSON payload와
    ROS std_msgs/String이 ROS2DDS를 통해 전달된
    CDR payload 둘 다 허용한다.
    """

    # --------------------------------------------------------
    # 1. 순수 JSON 먼저 시도
    # --------------------------------------------------------

    try:

        text = payload.decode("utf-8").strip()

        if text.startswith("{") and text.endswith("}"):

            return json.loads(text)

    except Exception:

        pass

    # --------------------------------------------------------
    # 2. CDR 내부 JSON 검색
    # --------------------------------------------------------

    try:

        text = payload.decode(
            "utf-8",
            errors="ignore",
        )

        match = re.search(
            r"\{.*\}",
            text,
        )

        if match:

            return json.loads(match.group(0))

    except Exception:

        pass

    return None


# ============================================================
# Telemetry Callback
# ============================================================


def _telemetry_listener(
    sample,
) -> None:

    try:

        topic = str(sample.key_expr)

        payload = sample.payload.to_bytes()

        data = _extract_json(payload)

        if not data:

            return

        # ----------------------------------------------------
        # robot1/telemetry
        # rt/robot1/telemetry
        # 둘 다 대응
        # ----------------------------------------------------

        parts = [part for part in topic.split("/") if (part and part != "rt")]

        raw_robot_id = data.get(
            "robot_id",
            (parts[0] if parts else "robot1"),
        )

        robot_id = normalize_robot_id(str(raw_robot_id))

        x = float(
            data.get(
                "x",
                0.0,
            )
        )

        y = float(
            data.get(
                "y",
                0.0,
            )
        )

        yaw = float(
            data.get(
                "yaw",
                0.0,
            )
        )

        battery = float(
            data.get(
                "battery",
                100.0,
            )
        )

        status = str(
            data.get(
                "status",
                "ONLINE",
            )
        )

        telemetry = {
            "robot_id": robot_id,
            "ui_id": to_ui_robot_id(robot_id),
            "x": x,
            "y": y,
            "yaw": yaw,
            "battery": battery,
            "status": status,
        }

        if _loop is None:

            return

        # ----------------------------------------------------
        # DB
        # ----------------------------------------------------

        asyncio.run_coroutine_threadsafe(
            upsert_robot_state(
                robot_id,
                x,
                y,
                yaw,
                battery,
                status,
            ),
            _loop,
        )

        # ----------------------------------------------------
        # Frontend WebSocket
        # ----------------------------------------------------

        asyncio.run_coroutine_threadsafe(
            manager.broadcast(
                {
                    "type": "telemetry",
                    "data": telemetry,
                }
            ),
            _loop,
        )

    except Exception as exc:

        print(" -> [WARN] " "Zenoh telemetry 파싱 실패: " f"{exc}")


async def publish_telemetry(
    telemetry: dict[str, Any],
) -> None:
    """Publish simulator telemetry through the same dashboard contract."""
    robot_id = normalize_robot_id(str(telemetry["robot_id"]))
    data = {
        **telemetry,
        "robot_id": robot_id,
        "ui_id": to_ui_robot_id(robot_id),
    }
    await manager.broadcast({"type": "telemetry", "data": data})
    if mode_manager.mode == "real":
        try:
            await upsert_robot_state(
                robot_id,
                float(data["x"]),
                float(data["y"]),
                float(data["yaw"]),
                float(data["battery"]),
                str(data["status"]),
            )
        except Exception:
            logging.getLogger(__name__).exception(
                "Robot telemetry persistence failed: %s", robot_id
            )


# ============================================================
# Zenoh Startup
# ============================================================


def start_zenoh(
    event_loop: asyncio.AbstractEventLoop,
) -> None:

    global _loop
    global _session
    global _subscriber

    _loop = event_loop

    if _session is not None:

        return

    try:

        config = zenoh.Config()

        # ----------------------------------------------------
        # Main zenohd에만 연결
        # ----------------------------------------------------

        config.insert_json5(
            "mode",
            '"client"',
        )

        config.insert_json5(
            "connect/endpoints",
            json.dumps([ZENOH_ENDPOINT]),
        )

        # ----------------------------------------------------
        # 다른 Zenoh peer 자동 discovery 차단
        # ----------------------------------------------------

        config.insert_json5(
            "scouting/multicast/enabled",
            "false",
        )

        config.insert_json5(
            "scouting/gossip/enabled",
            "false",
        )

        _session = zenoh.open(config)

        # ----------------------------------------------------
        # FMS Telemetry
        # ----------------------------------------------------

        _subscriber = _session.declare_subscriber(
            "**/telemetry",
            _telemetry_listener,
        )

        print(
            " -> FMS Native Zenoh 활성화 완료 "
            f"(endpoint={ZENOH_ENDPOINT}, "
            f"zid={_session.zid()})"
        )

    except Exception as exc:

        _session = None
        _subscriber = None

        print(" -> [WARN] " "Native Zenoh 연결 실패. " "Map/API는 계속 실행: " f"{exc}")


# ============================================================
# Zenoh Shutdown
# ============================================================


def stop_zenoh() -> None:

    global _session
    global _subscriber
    global _loop

    try:

        if _subscriber is not None:

            _subscriber.undeclare()

    except Exception:

        pass

    try:

        if _session is not None:

            _session.close()

    except Exception:

        pass

    _subscriber = None
    _session = None
    _loop = None

    print(" -> FMS Native Zenoh 종료")
