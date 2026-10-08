from typing import Literal

from pydantic import BaseModel


class OrderItems(BaseModel):
    A: int
    B: int
    C: int
    D: int


class CreateOrderRequest(BaseModel):
    robot_id: str
    items: OrderItems
    total_quantity: int
    workstation_node: str

    driving_mode: Literal["standard", "llm"] = "standard"
    selector: Literal["ollama", "laya", "kev"] | None = None
    model: str | None = None
