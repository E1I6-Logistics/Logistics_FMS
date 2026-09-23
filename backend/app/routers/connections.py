from __future__ import annotations

from fastapi import APIRouter

from ..services.mock_data import mock_fms


router = APIRouter(prefix="/api/connections", tags=["connections"])


@router.get("")
async def get_connections():
    """Return deterministic connection data required by the frontend."""
    return {"devices": mock_fms.connections()}
