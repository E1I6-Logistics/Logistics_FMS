from __future__ import annotations

from fastapi import APIRouter

from ..services.mock_data import mock_fms
from ..services.mode_service import mode_manager


router = APIRouter(prefix="/api/robots", tags=["robots"])


@router.get("")
async def fetch_robots():
    """Return deterministic robot data required by the frontend."""
    return mock_fms.robot_snapshots(mode_manager.mode)
