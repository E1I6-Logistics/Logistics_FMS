from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class ClientLog(BaseModel):
    level: Literal["warning", "error"]
    event: str = Field(min_length=1, max_length=80)
    message: str = Field(min_length=1, max_length=2000)
    url: str | None = Field(default=None, max_length=500)
    client_time: str | None = Field(default=None, max_length=80)
    details: dict[str, str | int | float | bool | None] = Field(default_factory=dict)

