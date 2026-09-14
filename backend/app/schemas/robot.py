from __future__ import annotations

import re
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


# ============================================================
# Robot ID 변환
# ============================================================

_BACKEND_ID_RE = re.compile(
    r"^robot0*([1-9][0-9]*)$",
    re.IGNORECASE,
)

_UI_ID_RE = re.compile(
    r"^R-?0*([1-9][0-9]*)$",
    re.IGNORECASE,
)


def normalize_robot_id(
    robot_id: str,
) -> str:
    """
    다음 형식을 모두 허용:

    robot1
    robot01
    R-01
    R01
    R1

    반환값은 항상:

    robot1
    robot2
    robot3
    """

    value = str(robot_id).strip()

    match = _BACKEND_ID_RE.fullmatch(value)

    if match:
        number = int(match.group(1))

        return f"robot{number}"

    match = _UI_ID_RE.fullmatch(value)

    if match:
        number = int(match.group(1))

        return f"robot{number}"

    raise ValueError(
        f"지원하지 않는 robot_id 형식: {robot_id}"
    )


def to_ui_robot_id(
    robot_id: str,
) -> str:

    backend_id = normalize_robot_id(robot_id)

    number = int(
        backend_id.removeprefix("robot")
    )

    return f"R-{number:02d}"


# ============================================================
# Robot 상태 Schema
# ============================================================

class RobotState(BaseModel):

    robot_id: str

    ui_id: str

    status: str = "IDLE"

    battery: float = Field(
        default=100.0,
        ge=0.0,
    )

    x: float = 0.0

    y: float = 0.0

    yaw: float = 0.0

    updated_at: Optional[datetime] = None


# ============================================================
# Dashboard telemetry event
# ============================================================

class TelemetryEvent(BaseModel):

    type: str = "telemetry"

    data: RobotState