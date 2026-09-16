from __future__ import annotations

from fastapi import (
    APIRouter,
    HTTPException,
)

from ..database.database import (
    get_all_robots,
    get_robot,
)

from ..schemas.robot import (
    normalize_robot_id,
    to_ui_robot_id,
)


router = APIRouter(
    prefix="/api/robots",
    tags=["robots"],
)


# ============================================================
# DB -> Frontend 변환
# ============================================================

def _serialize(
    row: dict,
) -> dict:

    result = dict(
        row
    )

    robot_id = normalize_robot_id(
        str(
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

@router.get("")
async def fetch_robots():

    rows = (
        await get_all_robots()
    )

    return [
        _serialize(row)
        for row in rows
    ]


# ============================================================
# 특정 로봇
# ============================================================

@router.get("/{robot_id}")
async def fetch_robot(
    robot_id: str,
):

    try:

        backend_id = normalize_robot_id(
            robot_id
        )

    except ValueError as exc:

        raise HTTPException(
            status_code=400,
            detail=str(exc),
        ) from exc

    row = await get_robot(
        backend_id
    )

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