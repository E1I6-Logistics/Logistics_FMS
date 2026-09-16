from __future__ import annotations

from fastapi import (
    APIRouter,
    HTTPException,
)

from ..schemas.command import (
    GoalCoordinateRequest,
    GoalNodeRequest,
    StopRequest,
)

from ..services.route_graph import (
    get_node,
)

from ..services.ros_gateway import (
    ros_gateway,
)

from ..services.zenoh_service import (
    status_snapshot as zenoh_status_snapshot,
)


router = APIRouter(
    prefix="/api/command",
    tags=["commands"],
)


# ============================================================
# ROS Gateway 확인
# ============================================================

def _require_ros() -> None:

    if not ros_gateway.active:

        raise HTTPException(
            status_code=503,
            detail="ROS Gateway inactive",
        )


# ============================================================
# Command 상태
# ============================================================

@router.get("/status")
async def command_status():

    return {

        "ros":
            ros_gateway.status_snapshot(),

        "zenoh":
            zenoh_status_snapshot(),
    }


# ============================================================
# Backend Capability
# ============================================================

@router.get("/capabilities")
async def command_capabilities():

    return {

        # ----------------------------------------------------
        # ROS Topic
        # ----------------------------------------------------

        "cmdVel":
            True,

        "stop":
            True,

        # ----------------------------------------------------
        # ROS Action
        # ----------------------------------------------------

        "coordinateGoal":
            True,

        "nodeMove":
            True,

        "navigateToPose":
            True,

        # ----------------------------------------------------
        # 추후 구현
        # ----------------------------------------------------

        "assign":
            False,

        "charge":
            False,

        "manualModeSwitch":
            False,

        # ----------------------------------------------------
        # Communication
        # ----------------------------------------------------

        "rosGateway":
            True,

        "nativeZenohTelemetry":
            True,
    }


# ============================================================
# 좌표 기반 Nav2 Goal
# ============================================================

@router.post("/goal")
async def send_coordinate_goal(
    payload: GoalCoordinateRequest,
):

    _require_ros()

    try:

        return await ros_gateway.navigate_to_pose(
            payload.robot_id,
            payload.target_x,
            payload.target_y,
            frame_id="map",
        )

    except ValueError as exc:

        raise HTTPException(
            status_code=400,
            detail=str(exc),
        ) from exc

    except RuntimeError as exc:

        raise HTTPException(
            status_code=503,
            detail=str(exc),
        ) from exc

    except Exception as exc:

        raise HTTPException(
            status_code=500,
            detail=str(exc),
        ) from exc


# ============================================================
# Node 기반 Nav2 Goal
# ============================================================

@router.post("/goal-node")
async def send_node_goal(
    payload: GoalNodeRequest,
):

    _require_ros()

    try:

        # ----------------------------------------------------
        # GeoJSON Node 검색
        # ----------------------------------------------------

        node = get_node(
            payload.node_id
        )

        # ----------------------------------------------------
        # Node 좌표 -> Nav2 NavigateToPose
        # ----------------------------------------------------

        result = (
            await ros_gateway.navigate_to_pose(
                payload.robot_id,
                node["x"],
                node["y"],
                frame_id=node["frame"],
            )
        )

        # ----------------------------------------------------
        # Frontend 확인용 Node 정보
        # ----------------------------------------------------

        result["node"] = {

            "id":
                node["id"],

            "x":
                node["x"],

            "y":
                node["y"],

            "frame":
                node["frame"],
        }

        return result

    except KeyError as exc:

        raise HTTPException(
            status_code=404,
            detail=str(exc),
        ) from exc

    except ValueError as exc:

        raise HTTPException(
            status_code=400,
            detail=str(exc),
        ) from exc

    except RuntimeError as exc:

        raise HTTPException(
            status_code=503,
            detail=str(exc),
        ) from exc

    except Exception as exc:

        raise HTTPException(
            status_code=500,
            detail=str(exc),
        ) from exc


# ============================================================
# Robot Stop
# ============================================================

@router.post("/stop")
async def stop_robot(
    payload: StopRequest,
):

    _require_ros()

    try:

        return ros_gateway.stop_robot(
            payload.robot_id
        )

    except ValueError as exc:

        raise HTTPException(
            status_code=400,
            detail=str(exc),
        ) from exc

    except RuntimeError as exc:

        raise HTTPException(
            status_code=503,
            detail=str(exc),
        ) from exc

    except Exception as exc:

        raise HTTPException(
            status_code=500,
            detail=str(exc),
        ) from exc