from __future__ import annotations

from fastapi import APIRouter, HTTPException

from ..schemas.command import GoalCoordinateRequest, GoalNodeRequest, StopRequest
from ..services.mock_data import mock_fms
from ..services.mode_service import mode_manager


router = APIRouter(prefix="/api/command", tags=["commands"])


@router.post("/goal")
async def send_coordinate_goal(payload: GoalCoordinateRequest):
    try:
        result = mock_fms.navigate_to_pose(
            payload.robot_id,
            payload.target_x,
            payload.target_y,
        )
        result["mode"] = mode_manager.mode
        return result
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/goal-node")
async def send_node_goal(payload: GoalNodeRequest):
    try:
        result = mock_fms.navigate_to_node(payload.robot_id, payload.node_id)
        result["mode"] = mode_manager.mode
        return result
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/stop")
async def stop_robot(payload: StopRequest):
    try:
        result = mock_fms.stop_robot(payload.robot_id)
        result["mode"] = mode_manager.mode
        return result
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
