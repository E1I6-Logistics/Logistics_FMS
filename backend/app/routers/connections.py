from __future__ import annotations

from fastapi import APIRouter

from ..services.mock_data import mock_fms
from ..services.mode_service import mode_manager
from ..services.zenoh_connection_manager import zenoh_connection_manager
from ..ros2.ros_gateway import ros_gateway

router = APIRouter(prefix="/api/connections", tags=["connections"])


@router.get("")
async def get_connections():
    if mode_manager.mode == "simulation":
        return {"devices": mock_fms.connections()}

    devices = zenoh_connection_manager.connections()

    ros_gateway.sync_connected_robots(devices)

    return {"devices": devices}
