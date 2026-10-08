"""Enabled route models shared by the dashboard and route execution."""
from __future__ import annotations

import json
from pathlib import Path

CONFIG_PATH = Path(__file__).resolve().parents[3] / "simulation" / "evaluation" / "selector_iterative_benchmark.json"


def enabled_route_models() -> dict[str, list[dict[str, str]]]:
    """Read the benchmark allowlist on each request so UI and server agree."""
    config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    ollama = [
        {"selector": "ollama", "model": item["name"]}
        for item in config.get("models", [])
        if item.get("enabled") is True
    ]
    decision = [
        {"selector": item["selector"], "model": item["name"]}
        for item in config.get("decision_models", [])
        if item.get("enabled") is True and item.get("selector") in {"laya", "kev"}
    ]
    return {"ollama": ollama, "decision_model": decision}


def require_enabled_model(selector: str, model: str) -> None:
    groups = enabled_route_models()
    if not any(
        item["selector"] == selector and item["model"] == model
        for group in groups.values() for item in group
    ):
        raise ValueError(f"사용할 수 없는 경로 모델입니다: {selector}/{model}")
