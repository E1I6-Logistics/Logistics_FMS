from fastapi import APIRouter, HTTPException

from ..schemas.order import CreateOrderRequest
from ..services.order_manager import order_manager

router = APIRouter(prefix="/api/orders", tags=["orders"])


@router.post("")
async def create_order(payload: CreateOrderRequest):
    try:
        return order_manager.create_order(
            robot_id=payload.robot_id,
            items=payload.items.model_dump(),
            total_quantity=payload.total_quantity,
            workstation_node=payload.workstation_node,
        )

    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
