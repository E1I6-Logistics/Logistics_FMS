from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..services.mode_service import mode_manager
from ..services.websocket_manager import manager
from .robots import fetch_robots
from ..schemas.robot import to_ui_robot_id

router = APIRouter(prefix="/api/mode", tags=["mode"])


class ModeRequest(BaseModel):
    mode: Literal["real", "simulation"]


def _snapshot() -> dict[str, object]:
    return {
        "mode": mode_manager.mode,
        "real_available": True,
        "simulation_active": mode_manager.mode == "simulation",
        "using_mock": mode_manager.mode == "simulation",
    }


@router.get("")
async def get_mode():
    return _snapshot()


@router.put("")
async def set_mode(payload: ModeRequest):
    from ..services.scenario_service import scenario_manager
    try:
        scenario_manager.ensure_available()
    except ValueError as exc:
        raise HTTPException(409, detail=str(exc)) from exc
    # 실제 모드 전환에서는 시뮬레이션 모듈을 로드하지 않는다.
    if payload.mode == "simulation":
        from ..services.mock_data import mock_fms
        states = mock_fms.robot_snapshots(payload.mode)
    else:
        states = None
    mode_manager.set_mode(payload.mode)
    if states is None:
        states = await fetch_robots()
        for state in states:
            state["ui_id"] = to_ui_robot_id(state["robot_id"])
    await manager.broadcast(
        {"type": "system", "data": {
            "mode": mode_manager.mode,
            "source": "mock" if mode_manager.mode == "simulation" else "ros2",
        }}
    )
    for state in states:
        await manager.broadcast({"type": "telemetry", "data": state})
    return _snapshot()
