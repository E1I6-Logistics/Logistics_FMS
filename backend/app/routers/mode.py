from __future__ import annotations

from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel

from ..services.mock_data import mock_fms
from ..services.mode_service import mode_manager
from ..services.websocket_manager import manager


router = APIRouter(prefix="/api/mode", tags=["mode"])


class ModeRequest(BaseModel):
    mode: Literal["real", "simulation"]


def _snapshot() -> dict[str, object]:
    return {
        "mode": mode_manager.mode,
        "real_available": True,
        "simulation_active": mode_manager.mode == "simulation",
        "using_mock": True,
    }


@router.get("")
async def get_mode():
    return _snapshot()


@router.put("")
async def set_mode(payload: ModeRequest):
    mode_manager.set_mode(payload.mode)
    await manager.broadcast(
        {"type": "system", "data": {"mode": mode_manager.mode, "source": "mock"}}
    )
    for state in mock_fms.robot_snapshots(mode_manager.mode):
        await manager.broadcast({"type": "telemetry", "data": state})
    return _snapshot()
