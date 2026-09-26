"""Read-only access to the static GeoJSON shown by the frontend."""

from __future__ import annotations

import json
from typing import Any

from ..config import ROUTE_GRAPH_PATH

"""
{
    # Node 좌표 및 타입 정보
    "geometry": {
        "coordinates": [1.4094749689102173, 0.03032200038433075],
        "type": "Point"
    },
    # Node ID 및 속성 정보
    "properties": {
        "frame": "map",
        "id": 13
    },
    "type": "Feature"
},
{
    # Edge 정보
    "geometry": {
        "type": "MultiLineString"
    },
    # Edge ID 및 속성 정보
    "properties": {
        "cost": 0.0,
        "endid": 3,
        "id": 14,
        
        # 이 Edge에 저장된 cost가 Edge Cost Function들에 의해 재계산/대체될 수 있도록 허용
        "overridable": true,
        "startid": 0
    },
    "type": "Feature"
}
"""


# Route Graph GeoJSON 파일 로드 기능
def load_route_graph() -> dict[str, Any]:
    if not ROUTE_GRAPH_PATH.exists():
        raise FileNotFoundError(f"Route Graph 파일 없음: {ROUTE_GRAPH_PATH}")
    with ROUTE_GRAPH_PATH.open("r", encoding="utf-8") as file:
        graph = json.load(file)
    if graph.get("type") != "FeatureCollection":
        raise ValueError("Route Graph는 GeoJSON FeatureCollection 형식이어야 합니다.")
    return graph


# Node Features 추출 기능
def _node_features(graph: dict[str, Any]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for feature in graph.get("features", []):
        geometry = feature.get("geometry") or {}
        properties = feature.get("properties") or {}
        node_id = properties.get("id")
        coordinates = geometry.get("coordinates")
        if (
            geometry.get("type") == "Point"
            and node_id is not None
            and isinstance(coordinates, list)
            and len(coordinates) >= 2
        ):
            result[str(node_id)] = feature
    return result


# Node 정보 조회 기능 -> 문자열 또는 정수를 Node ID로 조회 가능
def get_node(node_id: str | int) -> dict[str, Any]:
    feature = _node_features(load_route_graph()).get(str(node_id))
    if feature is None:
        raise KeyError(f"존재하지 않는 route node: {node_id}")
    coordinates = feature["geometry"]["coordinates"]
    properties = feature.get("properties") or {}
    return {
        "id": properties.get("id"),
        "x": float(coordinates[0]),
        "y": float(coordinates[1]),
        "frame": properties.get("frame", "map"),
        "properties": properties,
    }


# Node 목록 조회 기능 -> ID 기준 정렬, 문자열 ID는 뒤로
def list_nodes() -> list[dict[str, Any]]:
    nodes = [get_node(node_id) for node_id in _node_features(load_route_graph())]

    def sort_key(node: dict[str, Any]):
        try:
            return 0, int(node["id"])
        except (TypeError, ValueError):
            return 1, str(node["id"])

    return sorted(nodes, key=sort_key)
