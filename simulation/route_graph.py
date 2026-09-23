"""Route graph access for standalone simulation and LLM experiments."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

ROUTE_GRAPH_PATH = (
    Path(__file__).resolve().parents[1]
    / "routes"
    / os.getenv("FMS_ROUTE_GRAPH", "test.geojson")
)


def load_route_graph() -> dict[str, Any]:
    if not ROUTE_GRAPH_PATH.is_file():
        raise FileNotFoundError(f"Route Graph 파일 없음: {ROUTE_GRAPH_PATH}")
    with ROUTE_GRAPH_PATH.open("r", encoding="utf-8") as file:
        graph = json.load(file)
    if graph.get("type") != "FeatureCollection":
        raise ValueError("Route Graph는 GeoJSON FeatureCollection 형식이어야 합니다.")
    return graph


def node_lookup(graph: dict[str, Any] | None = None) -> dict[str, dict[str, Any]]:
    """Return Point features indexed by their node ID."""
    source = graph if graph is not None else load_route_graph()
    result: dict[str, dict[str, Any]] = {}
    for feature in source.get("features", []):
        geometry = feature.get("geometry") or {}
        properties = feature.get("properties") or {}
        coordinates = geometry.get("coordinates")
        node_id = properties.get("id")
        if (
            geometry.get("type") == "Point"
            and node_id is not None
            and isinstance(coordinates, list)
            and len(coordinates) >= 2
        ):
            result[str(node_id)] = feature
    return result
