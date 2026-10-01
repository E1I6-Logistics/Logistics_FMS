from __future__ import annotations

from fastapi import APIRouter, HTTPException

from ..schemas.order import CreateOrderRequest
from ..services.order_service import order_service
from ..ros2.ros_gateway import ros_gateway

router = APIRouter(prefix="/api/orders", tags=["orders"])


@router.post("")
async def create_order(request: CreateOrderRequest):

    try:
        # ====================================================
        # 1. 주문 저장 + 픽업 Node 결정
        # ====================================================

        order_result = order_service.create_order(
            robot_id=request.robot_id,
            items=request.items.model_dump(),
            workstation_node=request.workstation_node,
        )

        # ====================================================
        # 2. 첫 번째 픽업 목적지 확인
        # ====================================================

        destination_node = order_result["destination_node"]

        # ====================================================
        # 3. 실제 Robot에 목적지 전송
        # ====================================================

        navigation_result = ros_gateway.navigate_to_node(
            robot_id=order_result["robot_id"], node_id=destination_node
        )

        # ====================================================
        # 4. Frontend에 결과 반환
        # ====================================================

        return {
            "robot_id": order_result["robot_id"],
            "items": order_result["items"],
            "total_quantity": request.total_quantity,
            "pickup_nodes": order_result["pickup_nodes"],
            "workstation_node": order_result["workstation_node"],
            "destination_node": destination_node,
            "status": "PROCESSING",
            "navigation": navigation_result,
        }

    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
