from fastapi import APIRouter

from ..services.mqtt_manager import mqtt_manager
from ..services.map_service import world_to_pixel

OMX_POSITIONS = {
    "omx1": (0.8085766434669495, -0.521459),
    "omx2": (1.5943385362625122, -0.521459),
    "omx3": (1.989379, 0.265518),
    "omx4": (1.989379, 0.629562),
}

router = APIRouter(prefix="/api/omx", tags=["omx"])


@router.get("")
async def get_omx_devices():
    result = []

    for omx_id, omx in mqtt_manager.get_all_omx().items():
        position = OMX_POSITIONS.get(omx_id)

        if position is None:
            continue

        world_x, world_y = position
        pixel_x, pixel_y = world_to_pixel(world_x, world_y)

        result.append(
            {
                "omx_id": omx_id,
                "connected": omx.connected,
                "x": world_x,
                "y": world_y,
                "pixel_x": pixel_x,
                "pixel_y": pixel_y,
            }
        )

    return result
