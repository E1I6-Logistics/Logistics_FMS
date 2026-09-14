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

from ..services.zenoh_service import (
    is_ready,
    publish_goal,
    publish_stop,
    status_snapshot,
)


router = APIRouter(
    prefix="/api/command",
    tags=["commands"],
)


# ============================================================
# Zenoh 확인
# ============================================================

def _require_zenoh() -> None:

    if not is_ready():

        raise HTTPException(
            status_code=503,
            detail="Zenoh session inactive",
        )


# ============================================================
# Command 상태
# ============================================================

@router.get("/status")
async def command_status():

    return status_snapshot()


# ============================================================
# 현재 Backend가 실제 지원하는 기능
# ============================================================

@router.get("/capabilities")
async def command_capabilities():

    return {

        "nodeMove": True,

        "coordinateGoal": True,

        "stop": True,

        "cmdVel": True,

        # 아직 실제 프로토콜 없음
        "assign": False,

        "charge": False,

        "manualModeSwitch": False,
    }


# ============================================================
# 좌표 기반 Goal
# ============================================================

@router.post("/goal")
async def send_coordinate_goal(
    payload: GoalCoordinateRequest,
):

    _require_zenoh()

    try:

        return publish_goal(
            payload.robot_id,
            payload.target_x,
            payload.target_y,
        )

    except ValueError as exc:

        raise HTTPException(
            status_code=400,
            detail=str(exc),
        ) from exc

    except Exception as exc:

        raise HTTPException(
            status_code=500,
            detail=str(exc),
        ) from exc


# ============================================================
# Node 기반 Goal
# ============================================================

@router.post("/goal-node")
async def send_node_goal(
    payload: GoalNodeRequest,
):

    _require_zenoh()

    try:

        # Node ID를 GeoJSON에서 찾음
        node = get_node(
            payload.node_id
        )

        # 실제 로봇에는 x/y 전달
        result = publish_goal(
            payload.robot_id,
            node["x"],
            node["y"],
        )

        # Frontend 확인용
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

    _require_zenoh()

    try:

        result = publish_stop(
            payload.robot_id
        )

        result[
            "message"
        ] = (
            "정지 cmd_vel 전송 완료"
        )

        return result

    except ValueError as exc:

        raise HTTPException(
            status_code=400,
            detail=str(exc),
        ) from exc

    except Exception as exc:

        raise HTTPException(
            status_code=500,
            detail=str(exc),
        ) from exc