from __future__ import annotations

from fastapi import APIRouter

from ..services.mock_data import mock_fms
from ..services.mode_service import mode_manager
from ..services.fleet_manager import fleet_manager
from ..services.map_service import world_to_pixel

router = APIRouter(prefix="/api/robots", tags=["robots"])


@router.get("")
async def fetch_robots():
    # Simulation 모드
    if mode_manager.mode == "simulation":
        return mock_fms.robot_snapshots(mode_manager.mode)

    # Real 모드
    result = []
    for robot in fleet_manager.get_all_robots():

        pixel_x = None
        pixel_y = None

        # AMCL 위치를 아직 받지 못했다면 좌표 변환하지 않음
        if robot.x is not None and robot.y is not None:
            pixel_x, pixel_y = world_to_pixel(robot.x, robot.y)

        result.append(
            {
                "robot_id": robot.robot_id,
                "status": robot.state.value,
                "battery": robot.battery,
                "x": robot.x,
                "y": robot.y,
                "yaw": robot.yaw,
                "current_node": robot.current_node,
                "route": robot.route,
                "pixel_x": pixel_x,
                "pixel_y": pixel_y,
                "connected": robot.connected,
                "map_pose_received": robot.x is not None and robot.y is not None,
                "mode": "real",
                "source": "ros2",
                "pose_source": "AMCL",
                "order_items": robot.order_items.copy(),
                "pickup_nodes": robot.pickup_nodes.copy(),
                "workstation_node": robot.workstation_node,
                "current_pickup_node": robot.current_pickup_node,
            }
        )

    return result
