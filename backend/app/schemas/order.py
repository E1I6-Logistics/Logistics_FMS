# API 요청 데이터 검증용 Pydantic 모델
from typing import Literal

from pydantic import BaseModel, Field, model_validator

# ============================================================
# 주문 물품
# ============================================================


class OrderItems(BaseModel):

    # 각 물품의 주문 수량
    A: int = Field(ge=0, le=5)
    B: int = Field(ge=0, le=5)
    C: int = Field(ge=0, le=5)
    D: int = Field(ge=0, le=5)


# ============================================================
# 주문 생성 요청
# ============================================================


class CreateOrderRequest(BaseModel):

    # 주문을 수행할 Robot ID
    robot_id: str

    # 주문 물품 및 수량
    items: OrderItems

    # 전체 주문 수량
    total_quantity: int = Field(ge=1, le=5)

    # 주문 완료 후 이동할 작업대 Node
    workstation_node: Literal["3", "4"]

    @model_validator(mode="after")
    def validate_total_quantity(self):
        calculated_total = sum(self.items.model_dump().values())
        if calculated_total != self.total_quantity:
            raise ValueError("total_quantity가 물품 수량 합계와 일치하지 않습니다.")
        return self
