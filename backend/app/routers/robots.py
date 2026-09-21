# 타입 힌트 지연 평가 기능 사용
from __future__ import annotations

# API Router 및 HTTP 예외 처리 기능 사용
from fastapi import (
    APIRouter,
    HTTPException,
)

# # Database Robot 상태 조회 기능 사용
# from ..database.database import (
#     get_all_robots,
#     get_robot,
# )

from ..services.robot_manager import robot_manager

# Robot ID 변환 기능 사용
from ..schemas.robot import (
    normalize_robot_id,
    to_ui_robot_id,
)
from ..services.simulation_gateway import simulation_gateway
from ..services.mode_service import mode_manager

from ..services.map_service import (
    world_to_pixel,
)


# Robot API Router 생성
router = APIRouter(
    prefix="/api/robots",
    tags=["robots"],
)


# ============================================================
# DB -> Frontend 변환
# ============================================================

# Database Robot 데이터를 Frontend 형식으로 변환 기능
def _serialize(
    row: dict,
) -> dict:

    # Database Row 복사본 생성
    result = dict(
        row
    )

    # Robot Pose의 ROS Map 좌표를 Web Map Pixel 좌표로 변환
    if (
        result.get("map_pose_received", False)
        and result.get("x") is not None
        and result.get("y") is not None
    ):
        pixel_x, pixel_y = world_to_pixel(
            result["x"],
            result["y"],
        )

        result["pixel_x"] = pixel_x
        result["pixel_y"] = pixel_y
    else:
        result["pixel_x"] = None
        result["pixel_y"] = None

    # Robot ID를 backend 표준 형식으로 변환
    robot_id = normalize_robot_id(
        str(
            # 표준 Robot ID 저장
            result["robot_id"]
        )
    )

    result[
        "robot_id"
    ] = robot_id

    result[
        "ui_id"
    ] = to_ui_robot_id(
        robot_id
    )
    result["mode"] = mode_manager.mode

    result["updated_at"] = result.get("last_update")

    result["map_pose_received"] = bool(
        result.get("map_pose_received", False)
    )

    result["connection_state"] = result.get(
        "connection_state", "OFFLINE",
    )

    return result


# ============================================================
# 전체 로봇
# ============================================================

# 전체 Robot 상태 조회 API 생성
@router.get("")
async def fetch_robots():

    if mode_manager.mode == "simulation":
        return simulation_gateway.robot_snapshots()

    rows = (
        # Database에서 전체 Robot 상태 조회
        # await get_all_robots()
        robot_manager.snapshots()
    )

    return [
        _serialize(row)
        for row in rows
    ]


# ============================================================
# 특정 로봇
# ============================================================

# 특정 Robot 상태 조회 API 생성
@router.get("/{robot_id}")
async def fetch_robot(
    robot_id: str,
):

    try:

        # 요청 Robot ID를 backend 표준 형식으로 변환
        backend_id = normalize_robot_id(
            robot_id
        )

    except ValueError as exc:

        raise HTTPException(
            status_code=400,
            detail=str(exc),
        ) from exc

    if mode_manager.mode == "simulation":
        try:
            return simulation_gateway.robot_snapshot(backend_id)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    # Database에서 특정 Robot 상태 조회
    # row = await get_robot(
    #     backend_id
    # )

    row = robot_manager.snapshot(backend_id)

    # Robot 상태 미존재 예외 처리
    if row is None:

        raise HTTPException(
            status_code=404,
            detail=(
                "로봇 상태 없음: "
                f"{backend_id}"
            ),
        )

    return _serialize(
        row
    )
