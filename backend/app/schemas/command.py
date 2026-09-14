from __future__ import annotations

from typing import Union

from pydantic import BaseModel


# ============================================================
# 좌표 기반 이동
# ============================================================

class GoalCoordinateRequest(BaseModel):

    robot_id: str

    target_x: float

    target_y: float


# ============================================================
# Node 기반 이동
# ============================================================

class GoalNodeRequest(BaseModel):

    robot_id: str

    node_id: Union[int, str]


# ============================================================
# 정지
# ============================================================

class StopRequest(BaseModel):

    robot_id: str


# ============================================================
# cmd_vel
# ============================================================

class CmdVelRequest(BaseModel):

    robot_id: str

    linear_x: float = 0.0

    angular_z: float = 0.0


# ============================================================
# 연결 차단 / 허용
# ============================================================

class DevicePayload(BaseModel):

    ip: str


# ============================================================
# 공통 명령 응답
# ============================================================

class CommandResponse(BaseModel):

    status: str

    robot_id: str

    ui_id: str

    topic: str

    message: str = ""