# 타입 힌트 지연 평가 기능 사용
from __future__ import annotations

# API Router 및 HTTP 예외 처리 기능 사용
from fastapi import (
    APIRouter,
    HTTPException,
)

# 장치 IP 요청 데이터 Schema 사용
from ..schemas.command import (
    DevicePayload,
)

# 장치 연결 상태 및 Firewall 제어 기능 사용
from ..services.network_service import (
    device_snapshot,
    firewall,
    seen_devices,
    valid_ip,
)


# Connection API Router 생성
router = APIRouter(
    prefix="/api/connections",
    tags=["connections"],
)


# ============================================================
# 연결 목록
# ============================================================

# 전체 장치 연결 상태 조회 API 생성
@router.get("")
async def get_connections():

    return {
        # 현재 장치 연결 상태 목록 응답 생성
        "devices":
            device_snapshot()
    }


# ============================================================
# Block
# ============================================================

# 특정 장치 연결 차단 API 생성
@router.post("/block")
async def block_connection(
    payload: DevicePayload,
):

    try:

        # 요청 IP 주소 형식 검증
        ip = valid_ip(
            payload.ip
        )

        # 확인된 장치 목록에 IP 추가
        seen_devices.add(
            ip
        )

        # iptables 기반 장치 통신 차단 또는 허용 실행
        firewall(
            "block",
            ip,
        )

        return {

            "status":
                "SUCCESS",

            "ip":
                ip,

            "devices":
                device_snapshot(),
        }

    except Exception as exc:

        raise HTTPException(
            status_code=500,
            detail=str(exc),
        ) from exc


# ============================================================
# Allow
# ============================================================

# 특정 장치 연결 허용 API 생성
@router.post("/allow")
async def allow_connection(
    payload: DevicePayload,
):

    try:

        ip = valid_ip(
            payload.ip
        )

        seen_devices.add(
            ip
        )

        firewall(
            "allow",
            ip,
        )

        return {

            "status":
                "SUCCESS",

            "ip":
                ip,

            "devices":
                device_snapshot(),
        }

    except Exception as exc:

        raise HTTPException(
            status_code=500,
            detail=str(exc),
        ) from exc