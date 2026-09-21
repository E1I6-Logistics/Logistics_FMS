from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..services.control_gateway import ros_gateway
from ..services.mode_service import mode_manager
from ..services.simulation_gateway import simulation_gateway
from ..services.zenoh_service import manager


router = APIRouter(
    prefix="/api/mode",
    tags=["mode"],
)


class ModeRequest(BaseModel):
    mode: Literal["real", "simulation"]


def _snapshot() -> dict[str, object]:
    return {
        "mode": mode_manager.mode,
        "real_available": ros_gateway.active,
        "simulation_active": simulation_gateway.active,
    }


@router.get("")
async def get_mode():
    return _snapshot()


@router.put("")
async def set_mode(payload: ModeRequest):
    requested_mode = payload.mode
    current_mode = mode_manager.mode

    if requested_mode == current_mode:
        return _snapshot()

    if requested_mode == "real":
        if not ros_gateway.active:
            raise HTTPException(
                status_code=503,
                detail="ROS Gateway inactive; real robot mode is unavailable",
            )
        await simulation_gateway.stop()
    else:
        simulation_gateway.start()

    mode_manager.set_mode(requested_mode)

    await manager.broadcast({
        "type": "system",
        "data": {
            "mode": mode_manager.mode,
            "ros": ros_gateway.status_snapshot(),
        },
    })

    return _snapshot()
