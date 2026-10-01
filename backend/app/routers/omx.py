from __future__ import annotations

from fastapi import APIRouter, HTTPException

from ..config import MQTT_ENABLED
from ..services.mqtt_manager import mqtt_manager


router = APIRouter(prefix="/api/omx", tags=["omx"])


@router.get("")
async def fetch_omx_devices():
    status = mqtt_manager.status()
    status["enabled"] = MQTT_ENABLED
    return {"mqtt": status, "devices": mqtt_manager.snapshots()}


@router.get("/{omx_id}")
async def fetch_omx_device(omx_id: str):
    for device in mqtt_manager.snapshots():
        if device["omx_id"] == omx_id:
            return device
    raise HTTPException(status_code=404, detail=f"OMX를 찾을 수 없습니다: {omx_id}")
