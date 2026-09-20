# 타입 힌트 지연 평가 기능 사용
from __future__ import annotations

# API Router 및 HTTP 예외 처리 기능 사용
from fastapi import (
    APIRouter,
    HTTPException,
)

# 명령 요청 데이터 Schema 사용
from ..schemas.command import (
    GoalCoordinateRequest,
    GoalNodeRequest,
    StopRequest,
)

# Route Graph Node 조회 기능 사용
from ..services.route_graph import (
    get_node,
)

# ROS2 명령 전송용 ROS Gateway 사용
from ..services.ros_gateway import (
    ros_gateway,
)

from ..services.simulation_gateway import (
    simulation_gateway,
)
from ..config import ROBOT_MODE

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

def _require_control() -> None:

    active = (
        simulation_gateway.active
        if ROBOT_MODE == "simulation"
        else ros_gateway.active
    )
    if not active:

        raise HTTPException(
            status_code=503,
            detail="Robot control gateway inactive",
        )


# ============================================================
# Command 상태
# ============================================================

# ROS Gateway 상태 조회 API 생성
@router.get("/status")
async def command_status():

    return {
        "ros":
            ros_gateway.status_snapshot(),
        "mode": ROBOT_MODE,
        "simulation":
            simulation_gateway.status_snapshot(),

        "zenoh":
            zenoh_status_snapshot(),
    }


# ============================================================
# Backend Capability
# ============================================================

# Backend 지원 기능 조회 API 생성
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
            ROBOT_MODE == "real",
        "simulationGateway":
            ROBOT_MODE == "simulation",

        "nativeZenohTelemetry":
            True,
    }


# ============================================================
# 좌표 기반 Nav2 Goal
# ============================================================

# 좌표 기반 Nav2 이동 요청 API 생성
@router.post("/goal")
async def send_coordinate_goal(
    payload: GoalCoordinateRequest,
):

    _require_control()

    try:

        if ROBOT_MODE == "simulation":
            return simulation_gateway.navigate_to_pose(
                payload.robot_id, payload.target_x, payload.target_y, frame_id="map"
            )
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

# Route Graph Node 기반 Nav2 이동 요청 API 생성
@router.post("/goal-node")
async def send_node_goal(
    payload: GoalNodeRequest,
):

    _require_control()

    try:

        # ----------------------------------------------------
        # GeoJSON Node 검색
        # ----------------------------------------------------

        # 요청한 Route Graph Node 정보 조회
        node = get_node(
            payload.node_id
        )

        # ----------------------------------------------------
        # Node 좌표 -> Nav2 NavigateToPose
        # ----------------------------------------------------

        if ROBOT_MODE == "simulation":
            result = simulation_gateway.navigate_to_node(payload.robot_id, payload.node_id)
        else:
            result = await ros_gateway.navigate_to_pose(
                payload.robot_id, node["x"], node["y"], frame_id=node["frame"]
            )

        # ----------------------------------------------------
        # Frontend 확인용 Node 정보
        # ----------------------------------------------------

        # Frontend 확인용 Node 정보 응답에 추가
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

# Robot 정지 요청 API 생성
@router.post("/stop")
async def stop_robot(
    payload: StopRequest,
):

    _require_control()

    try:

        if ROBOT_MODE == "simulation":
            return simulation_gateway.stop_robot(payload.robot_id)
        return ros_gateway.stop_robot(payload.robot_id)

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
