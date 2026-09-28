"""환경변수로 경로 후보 선택 구현을 생성한다."""

from __future__ import annotations

import os
from importlib import import_module
from pathlib import Path

from dotenv import load_dotenv

from .base import RouteSelector

load_dotenv(Path(__file__).resolve().parents[1] / ".env", override=False)

_SELECTORS: dict[str, tuple[str, str]] = {
    "ollaya_laya": (".ollaya_laya_selector", "OllayaLayaSelector"),
}


def get_selector() -> RouteSelector:
    selector_key = os.getenv("ROUTE_SELECTOR", "ollaya_laya").strip().lower()
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
