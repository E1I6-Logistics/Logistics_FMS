from __future__ import annotations

import asyncio
import json
import re
import struct
from typing import (
    Any,
    Optional,
)

import zenoh

from fastapi import WebSocket

from ..config import (
    CMD_VEL_MAX_ANGULAR,
    CMD_VEL_MAX_LINEAR,
    ZENOH_ENDPOINT,
    ZENOH_ROBOT_COUNT,
)

from ..database.database import (
    upsert_robot_state,
)

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

        self.active_connections: list[
            WebSocket
        ] = []

    async def connect(
        self,
        websocket: WebSocket,
    ) -> None:

        await websocket.accept()

        self.active_connections.append(
            websocket
        )

    def disconnect(
        self,
        websocket: WebSocket,
    ) -> None:

        if websocket in self.active_connections:

            self.active_connections.remove(
                websocket
            )

    async def broadcast(
        self,
        message: dict[str, Any],
    ) -> None:

        dead: list[
            WebSocket
        ] = []

        for connection in self.active_connections:

            try:

                await connection.send_json(
                    message
                )

            except Exception:

                dead.append(
                    connection
                )

        for connection in dead:

            self.disconnect(
                connection
            )


manager = ConnectionManager()


# ============================================================
# Zenoh Runtime State
# ============================================================

_session = None

_subscriber = None

_loop: Optional[
    asyncio.AbstractEventLoop
] = None

_publishers: dict[
    str,
    Any,
] = {}


# ============================================================
# Zenoh 상태
# ============================================================

def is_ready() -> bool:

    return (
        _session is not None
    )


def status_snapshot() -> dict[str, Any]:

    return {

        "connected":
            is_ready(),

        "endpoint":
            ZENOH_ENDPOINT,

        "dashboard_clients":
            len(
                manager.active_connections
            ),

        "publishers":
            sorted(
                _publishers.keys()
            ),
    }


# ============================================================
# Publisher cache
# ============================================================

def _publisher(
    topic: str,
):

    if _session is None:

        raise RuntimeError(
            "Zenoh session inactive"
        )

    if topic not in _publishers:

        _publishers[topic] = (
            _session.declare_publisher(
                topic
            )
        )

    return _publishers[
        topic
    ]


# ============================================================
# std_msgs/String CDR
# ============================================================

def _make_ros_string_cdr(
    text: str,
) -> bytes:

    utf8_bytes = (
        text.encode("utf-8")
        + b"\x00"
    )

    cdr_header = (
        b"\x00\x01\x00\x00"
    )

    length_prefix = struct.pack(
        "<I",
        len(utf8_bytes),
    )

    return (
        cdr_header
        + length_prefix
        + utf8_bytes
    )


# ============================================================
# geometry_msgs/TwistStamped CDR
# ============================================================

def make_twist_stamped_cdr(
    linear_x: float,
    angular_z: float,
) -> bytes:

    cdr_header = (
        b"\x00\x01\x00\x00"
    )

    # builtin_interfaces/Time
    sec = 0

    nanosec = 0

    # Header.frame_id = ""
    frame_id = b"\x00"

    frame_id_length = len(
        frame_id
    )

    body = struct.pack(
        "<iII",
        sec,
        nanosec,
        frame_id_length,
    )

    body += frame_id

    # 8 byte alignment
    padding = (
        8
        - (
            len(body)
            % 8
        )
    ) % 8

    body += (
        b"\x00"
        * padding
    )

    # geometry_msgs/Twist
    body += struct.pack(
        "<6d",

        float(linear_x),
        0.0,
        0.0,

        0.0,
        0.0,
        float(angular_z),
    )

    return (
        cdr_header
        + body
    )


# ============================================================
# Telemetry JSON 추출
# ============================================================

def _extract_json_from_cdr(
    payload: bytes,
) -> Optional[dict[str, Any]]:

    text = payload.decode(
        "utf-8",
        errors="ignore",
    )

    match = re.search(
        r"\{.*\}",
        text,
    )

    if not match:

        return None

    return json.loads(
        match.group(0)
    )


# ============================================================
# Zenoh Telemetry Callback
# ============================================================

def _telemetry_listener(
    sample,
) -> None:

    try:

        topic = str(
            sample.key_expr
        )

        data = _extract_json_from_cdr(
            sample.payload.to_bytes()
        )

        if not data:

            return

        # 예:
        #
        # robot1/telemetry
        #
        # 또는
        #
        # rt/robot1/telemetry

        parts = [
            part
            for part
            in topic.split("/")
            if (
                part
                and part != "rt"
            )
        ]

        raw_robot_id = data.get(
            "robot_id",
            (
                parts[0]
                if parts
                else "robot1"
            ),
        )

        robot_id = normalize_robot_id(
            str(raw_robot_id)
        )

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

            "robot_id":
                robot_id,

            "ui_id":
                to_ui_robot_id(
                    robot_id
                ),

            "x":
                x,

            "y":
                y,

            "yaw":
                yaw,

            "battery":
                battery,

            "status":
                status,
        }

        if _loop is not None:

            # DB update
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

            # Dashboard broadcast
            asyncio.run_coroutine_threadsafe(
                manager.broadcast(
                    {
                        "type":
                            "telemetry",

                        "data":
                            telemetry,
                    }
                ),
                _loop,
            )

    except Exception as exc:

        print(
            " -> [WARN] "
            "Zenoh telemetry 파싱 실패: "
            f"{exc}"
        )


# ============================================================
# Zenoh Startup
# ============================================================

def start_zenoh(
    event_loop:
        asyncio.AbstractEventLoop,
) -> None:

    global _loop, _session, _subscriber

    _loop = event_loop

    if _session is not None:

        return

    try:

        config = zenoh.Config()

        config.insert_json5(
            "mode",
            '"client"',
        )

        config.insert_json5(
            "connect/endpoints",
            json.dumps(
                [
                    ZENOH_ENDPOINT
                ]
            ),
        )

        config.insert_json5(
            "scouting/multicast/enabled",
            "false",
        )

        config.insert_json5(
            "scouting/gossip/enabled",
            "false",
        )

        _session = zenoh.open(
            config
        )

        # 모든 robot telemetry
        _subscriber = (
            _session.declare_subscriber(
                "**/telemetry",
                _telemetry_listener,
            )
        )

        # Publisher 사전 생성
        for index in range(
            1,
            ZENOH_ROBOT_COUNT + 1,
        ):

            robot_id = (
                f"robot{index}"
            )

            for suffix in (
                "goal",
                "cmd_vel",
            ):

                topic = (
                    f"{robot_id}/{suffix}"
                )

                _publishers[
                    topic
                ] = (
                    _session
                    .declare_publisher(
                        topic
                    )
                )

        print(
            " -> FMS Zenoh 세션 활성화 완료 "
            f"(endpoint={ZENOH_ENDPOINT}, "
            f"zid={_session.zid()})"
        )

    except Exception as exc:

        _session = None

        _subscriber = None

        _publishers.clear()

        print(
            " -> [WARN] "
            "Zenoh 연결 실패. "
            "Map/API만 실행: "
            f"{exc}"
        )


# ============================================================
# Zenoh Shutdown
# ============================================================

def stop_zenoh() -> None:

    global _session, _subscriber, _loop

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

    _publishers.clear()


# ============================================================
# Goal publish
# ============================================================

def publish_goal(
    robot_id: str,
    target_x: float,
    target_y: float,
) -> dict[str, Any]:

    backend_id = normalize_robot_id(
        robot_id
    )

    topic = (
        f"{backend_id}/goal"
    )

    body = {

        "x":
            float(target_x),

        "y":
            float(target_y),
    }

    json_text = json.dumps(
        body,
        ensure_ascii=False,
    )

    _publisher(
        topic
    ).put(
        _make_ros_string_cdr(
            json_text
        )
    )

    print(
        f" -> GOAL TX: "
        f"{topic} "
        f"payload={json_text}"
    )

    return {

        "status":
            "SUCCESS",

        "robot_id":
            backend_id,

        "ui_id":
            to_ui_robot_id(
                backend_id
            ),

        "topic":
            topic,

        "target":
            body,
    }


# ============================================================
# cmd_vel publish
# ============================================================

def publish_cmd_vel(
    robot_id: str,
    linear_x: float,
    angular_z: float,
) -> dict[str, Any]:

    backend_id = normalize_robot_id(
        robot_id
    )

    linear = max(
        -CMD_VEL_MAX_LINEAR,
        min(
            CMD_VEL_MAX_LINEAR,
            float(linear_x),
        ),
    )

    angular = max(
        -CMD_VEL_MAX_ANGULAR,
        min(
            CMD_VEL_MAX_ANGULAR,
            float(angular_z),
        ),
    )

    topic = (
        f"{backend_id}/cmd_vel"
    )

    _publisher(
        topic
    ).put(
        make_twist_stamped_cdr(
            linear,
            angular,
        )
    )

    return {

        "status":
            "SUCCESS",

        "robot_id":
            backend_id,

        "ui_id":
            to_ui_robot_id(
                backend_id
            ),

        "topic":
            topic,

        "linear_x":
            linear,

        "angular_z":
            angular,
    }


# ============================================================
# Stop
# ============================================================

def publish_stop(
    robot_id: str,
) -> dict[str, Any]:

    return publish_cmd_vel(
        robot_id,
        0.0,
        0.0,
    )