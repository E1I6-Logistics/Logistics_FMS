from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Mapping


class RouteSelector(ABC):
    """여러 경로 후보 중 하나를 선택하는 모델의 공통 인터페이스."""

    name = "base"

    @abstractmethod
    def select_route(
        self,
        state: str | dict[str, Any],
        candidates: Mapping[str, str],
    ) -> dict[str, Any]:
        """후보 ID와 설명을 받아 선택 결과와 신뢰도를 반환한다."""
        raise NotImplementedError
