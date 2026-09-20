# 타입 힌트 지연 평가 기능 사용
from __future__ import annotations

# API Router 및 HTTP 예외 처리 기능 사용
from fastapi import (
    APIRouter,
    HTTPException,
)

# Database Robot 상태 조회 기능 사용
from ..database.database import (
    get_all_robots,
    get_robot,
)

# Robot ID 변환 기능 사용
from ..schemas.robot import (
    normalize_robot_id,
    to_ui_robot_id,
)
from ..config import ROBOT_MODE
from ..services.simulation_gateway import simulation_gateway


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
    result["mode"] = ROBOT_MODE

    # 상태 갱신 시간이 존재하는 경우 처리
    if (
        result.get(
            "updated_at"
        )
        is not None
    ):

        result[
            "updated_at"
        ] = (
            result[
                "updated_at"
            ].isoformat()
        )

    return result


# ============================================================
# 전체 로봇
# ============================================================

# 전체 Robot 상태 조회 API 생성
@router.get("")
async def fetch_robots():

    if ROBOT_MODE == "simulation":
        return simulation_gateway.robot_snapshots()

    rows = (
        # Database에서 전체 Robot 상태 조회
        await get_all_robots()
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

    if ROBOT_MODE == "simulation":
        try:
            return simulation_gateway.robot_snapshot(backend_id)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    # Database에서 특정 Robot 상태 조회
    row = await get_robot(
        backend_id
    )

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
