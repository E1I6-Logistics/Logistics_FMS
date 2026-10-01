from __future__ import annotations

from backend.app.models import robot

from ..schemas.robot import normalize_robot_id
from .fleet_manager import fleet_manager

# ============================================================
# 물품별 픽업 Node
# ============================================================

ITEM_PICKUP_NODE = {
    "A": "5",
    "B": "5",
    "C": "6",
    "D": "6",
}


# ============================================================
# 주문 처리 Service
# ============================================================


class OrderService:

    def create_order(
        self,
        robot_id: str,
        items: dict[str, int],
        workstation_node: str,
    ) -> dict:

        # ----------------------------------------------------
        # 1. Robot ID 정규화
        # R-01 -> robot1
        # ----------------------------------------------------

        backend_robot_id = normalize_robot_id(robot_id)

        # ----------------------------------------------------
        # 2. 실제 Robot 객체 조회
        # ----------------------------------------------------

        robot = fleet_manager.get_robot(backend_robot_id)

        if robot is None:
            raise ValueError(f"Robot을 찾을 수 없습니다: {backend_robot_id}")

        # ----------------------------------------------------
        # 3. 주문 물품을 기준으로 픽업 Node 결정
        # ----------------------------------------------------

        pickup_nodes = []

        for item, quantity in items.items():

            # 수량이 없는 물품은 제외
            if quantity <= 0:
                continue

            pickup_node = ITEM_PICKUP_NODE.get(item)

            if pickup_node is None:
                raise ValueError(f"픽업 Node가 지정되지 않은 물품입니다: {item}")

            # 같은 Node 중복 방지
            if pickup_node not in pickup_nodes:
                pickup_nodes.append(pickup_node)

        # ----------------------------------------------------
        # 4. 주문 물품 존재 확인
        # ----------------------------------------------------

        if not pickup_nodes:
            raise ValueError("주문된 물품이 없습니다.")

        # ----------------------------------------------------
        # 5. 검증 완료 후 Robot 객체에 주문 저장
        # ----------------------------------------------------

        robot.order_items = items.copy()
        robot.pickup_nodes = pickup_nodes
        robot.workstation_node = str(workstation_node)
        # ----------------------------------------------------
        # 6. 첫 번째 목적지 결정
        # ----------------------------------------------------

        destination_node = pickup_nodes[0]
        # 현재 처리할 픽업 Node
        robot.current_pickup_node = destination_node

        # ----------------------------------------------------
        # 7. 처리 결과 반환
        # ----------------------------------------------------

        return {
            "robot_id": backend_robot_id,
            "items": robot.order_items.copy(),
            "pickup_nodes": robot.pickup_nodes.copy(),
            "workstation_node": robot.workstation_node,
            "destination_node": destination_node,
        }


order_service = OrderService()
