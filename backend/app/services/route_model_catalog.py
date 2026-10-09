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


def enabled_model_configuration(selector: str, model: str) -> dict:
    """Return the enabled model entry and its shared Ollama defaults."""
    require_enabled_model(selector, model)
    config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    entries = (
        config.get("models", []) if selector == "ollama"
        else config.get("decision_models", [])
    )
    entry = next(
        item for item in entries
        if item.get("name") == model
        and (selector == "ollama" or item.get("selector") == selector)
        and item.get("enabled") is True
    )
    if selector == "ollama":
        defaults = config.get("ollama_defaults", {})
        return {
            "host": entry.get("host", defaults.get("host")),
            "timeout_seconds": entry.get(
                "timeout_seconds", defaults.get("timeout_seconds", 60)
            ),
            "keep_alive": entry.get(
                "keep_alive", defaults.get("keep_alive", "5m")
            ),
            "think": entry.get("think", defaults.get("think")),
            "options": {
                **defaults.get("options", {}),
                **entry.get("options", {}),
            },
            "max_steps": config.get("settings", {}).get("max_steps"),
        }
    return {"max_steps": config.get("settings", {}).get("max_steps")}
