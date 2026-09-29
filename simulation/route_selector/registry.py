"""환경변수로 경로 후보 선택 구현을 생성한다."""

from __future__ import annotations

import os
from abc import ABC, abstractmethod
from importlib import import_module
from pathlib import Path
from typing import Any, Mapping

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[1] / ".env", override=False)


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


_SELECTORS: dict[str, tuple[str, str]] = {
    "laya": (".laya_selector", "LayaSelector"),
    "kev": (".kev_selector", "KevSelector"),
}


def get_selector() -> RouteSelector:
    selector_key = os.getenv("ROUTE_SELECTOR", "laya").strip().lower()
    if selector_key not in _SELECTORS:
        available = ", ".join(sorted(_SELECTORS))
        raise RuntimeError(
            f"알 수 없는 ROUTE_SELECTOR: '{selector_key}' (사용 가능: {available})"
        )

    module_name, class_name = _SELECTORS[selector_key]
    module = import_module(module_name, package=__package__)
    return getattr(module, class_name)()


def get_provider() -> RouteSelector:
    """기존 import를 깨지 않기 위한 get_selector 별칭."""
    return get_selector()
