# API 요청 데이터 검증용 Pydantic 모델
from pydantic import BaseModel

# ============================================================
# 주문 물품
# ============================================================


class OrderItems(BaseModel):

    # 각 물품의 주문 수량
    A: int
    B: int
    C: int
    D: int


# ============================================================
# 주문 생성 요청
# ============================================================


class CreateOrderRequest(BaseModel):

    # 주문을 수행할 Robot ID
    robot_id: str

    # 주문 물품 및 수량
    items: OrderItems

    # 전체 주문 수량
    total_quantity: int

    # 주문 완료 후 이동할 작업대 Node
    workstation_node: str
