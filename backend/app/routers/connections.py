from __future__ import annotations

from fastapi import (
    APIRouter,
    HTTPException,
)

from ..schemas.command import (
    DevicePayload,
)

from ..services.network_service import (
    device_snapshot,
    firewall,
    seen_devices,
    valid_ip,
)


router = APIRouter(
    prefix="/api/connections",
    tags=["connections"],
)


# ============================================================
# 연결 목록
# ============================================================

@router.get("")
async def get_connections():

    return {
        "devices":
            device_snapshot()
    }


# ============================================================
# Block
# ============================================================

@router.post("/block")
async def block_connection(
    payload: DevicePayload,
):

    try:

        ip = valid_ip(
            payload.ip
        )

        seen_devices.add(
            ip
        )

        firewall(
            "block",
            ip,
        )

        return {

            "status":
                "SUCCESS",

            "ip":
                ip,

            "devices":
                device_snapshot(),
        }

    except Exception as exc:

        raise HTTPException(
            status_code=500,
            detail=str(exc),
        ) from exc


# ============================================================
# Allow
# ============================================================

@router.post("/allow")
async def allow_connection(
    payload: DevicePayload,
):

    try:

        ip = valid_ip(
            payload.ip
        )

        seen_devices.add(
            ip
        )

        firewall(
            "allow",
            ip,
        )

        return {

            "status":
                "SUCCESS",

            "ip":
                ip,

            "devices":
                device_snapshot(),
        }

    except Exception as exc:

        raise HTTPException(
            status_code=500,
            detail=str(exc),
        ) from exc