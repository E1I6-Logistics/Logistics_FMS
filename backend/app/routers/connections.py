from __future__ import annotations

from fastapi import APIRouter
from starlette.concurrency import run_in_threadpool

from ..services.mock_data import mock_fms
from ..services.mode_service import mode_manager
from ..services.zenoh_connection_manager import zenoh_connection_manager
from ..ros2.ros_gateway import ros_gateway

router = APIRouter(prefix="/api/connections", tags=["connections"])


@router.get("")
async def get_connections():
    if mode_manager.mode == "simulation":
        return {"devices": mock_fms.connections()}

    # urllib-based Zenoh admin queries are blocking I/O. Keep them away from
    # FastAPI's event loop so dashboard and control WebSockets remain responsive.
    devices = await run_in_threadpool(zenoh_connection_manager.connections)

    ros_gateway.sync_connected_robots(devices)

    return {"devices": devices}
