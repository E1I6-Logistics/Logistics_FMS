"""Route graph loading, shortest-path planning, and path validation.

The simulator and evaluation harness share this module.  A stored edge
``weight`` is authoritative.  Legacy graphs without that field retain the old
positive-cost/coordinate fallback unless a caller requests strict weights.
"""

from __future__ import annotations

import heapq
import json
import math
import os
from pathlib import Path
from typing import Any


ROUTE_GRAPH_PATH = (
    Path(__file__).resolve().parents[2]
    / "routes"
    / os.getenv("FMS_ROUTE_GRAPH", "test.geojson")
)


def load_route_graph() -> dict[str, Any]:
    """Load and validate the configured GeoJSON route graph."""
    if not ROUTE_GRAPH_PATH.is_file():
        raise FileNotFoundError(f"Route Graph 파일 없음: {ROUTE_GRAPH_PATH}")
    with ROUTE_GRAPH_PATH.open("r", encoding="utf-8") as file:
        graph = json.load(file)
    if graph.get("type") != "FeatureCollection":
        raise ValueError("Route Graph는 GeoJSON FeatureCollection 형식이어야 합니다.")
    return graph


def node_lookup(
    graph: dict[str, Any] | None = None,
) -> dict[str, dict[str, Any]]:
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


def _resolve_edge_weight(
    properties: dict[str, Any],
    points: dict[int, tuple[float, float]],
    start: int,
    end: int,
    *,
    require_stored_weight: bool,
) -> float:
    """Resolve one edge weight while keeping legacy graphs compatible."""
    if "weight" in properties:
        weight = float(properties["weight"])
    elif require_stored_weight:
        raise ValueError(
            f"Edge {properties.get('id', f'{start}-{end}')}에 weight가 없습니다."
        )
    else:
        cost = float(properties.get("cost", 0.0))
        weight = cost if cost > 0 else math.dist(points[start], points[end])
    if not math.isfinite(weight) or weight < 0:
        raise ValueError("간선 weight는 0 이상의 유한한 숫자여야 합니다.")
    return weight


def build_route_inputs(
    graph: dict[str, Any],
    *,
    require_stored_weight: bool = False,
) -> tuple[dict[int, tuple[float, float]], list[tuple[int, int, float]]]:
    """Convert GeoJSON into node coordinates and resolved directed weights."""
    points = {
        int(node_id): (
            float(feature["geometry"]["coordinates"][0]),
            float(feature["geometry"]["coordinates"][1]),
        )
        for node_id, feature in node_lookup(graph).items()
    }
    if not points:
        raise ValueError("Route graph에 Point 노드가 없습니다.")

    edges: list[tuple[int, int, float]] = []
    for feature in graph.get("features", []):
        properties = feature.get("properties") or {}
        if properties.get("startid") is None or properties.get("endid") is None:
            continue
        start, end = int(properties["startid"]), int(properties["endid"])
        if start not in points or end not in points:
            continue
        edges.append(
            (
                start,
                end,
                _resolve_edge_weight(
                    properties,
                    points,
                    start,
                    end,
                    require_stored_weight=require_stored_weight,
                ),
            )
        )
    return points, edges


def plan_route(
    start_id: str,
    goal_id: str,
    graph: dict[str, Any] | None = None,
    *,
    require_stored_weight: bool = False,
) -> dict[str, Any]:
    """Calculate a directed shortest path from the resolved edge weights."""
    graph = graph if graph is not None else load_route_graph()
    nodes = node_lookup(graph)
    start_id, goal_id = str(start_id), str(goal_id)

    if start_id not in nodes or goal_id not in nodes:
        raise ValueError(f"존재하지 않는 경로 노드: {start_id} → {goal_id}")
    points = {
        key: tuple(map(float, node["geometry"]["coordinates"][:2]))
        for key, node in nodes.items()
    }
    integer_points = {int(key): value for key, value in points.items()}
    adjacency: dict[str, list[tuple[str, float, str]]] = {
        key: [] for key in nodes
    }
    for feature in graph.get("features", []):
        properties = feature.get("properties") or {}
        if properties.get("startid") is None or properties.get("endid") is None:
            continue
        start, end = str(properties["startid"]), str(properties["endid"])
        if start not in points or end not in points:
            continue
        weight = _resolve_edge_weight(
            properties,
            integer_points,
            int(start),
            int(end),
            require_stored_weight=require_stored_weight,
        )
        edge_id = str(properties.get("id", f"{start}-{end}"))
        adjacency[start].append((end, weight, edge_id))

    distances = {start_id: 0.0}
    previous: dict[str, tuple[str, str]] = {}
    queue = [(0.0, start_id)]
    while queue:
        distance, current = heapq.heappop(queue)
        if distance > distances[current]:
            continue
        if current == goal_id:
            break
        for neighbor, weight, edge_id in adjacency[current]:
            candidate = distance + weight
            if candidate < distances.get(neighbor, math.inf):
                distances[neighbor] = candidate
                previous[neighbor] = (current, edge_id)
                heapq.heappush(queue, (candidate, neighbor))

    if goal_id not in distances:
        raise ValueError(f"노드 {start_id}에서 {goal_id}까지 연결된 경로가 없습니다.")
    path, edge_ids = [goal_id], []
    while path[-1] != start_id:
        parent, edge_id = previous[path[-1]]
        path.append(parent)
        edge_ids.append(edge_id)
    path.reverse()
    edge_ids.reverse()
    return {
        "node_ids": path,
        "edge_ids": edge_ids,
        "waypoints": [points[key] for key in path],
        "cost": distances[goal_id],
    }


def build_compact_route_graph(
    graph: dict,
    source_graph: str,
    *,
    require_stored_weight: bool = False,
) -> dict:
    """Convert route GeoJSON into the smaller graph format sent to an LLM."""
    points, edges = build_route_inputs(
        graph, require_stored_weight=require_stored_weight
    )
    edge_weights = build_edge_weight_lookup(points, edges)
    return {
        "type": "CompactRouteGraph",
        "source_graph": source_graph,
        "directed": True,
        "weight_rule": (
            "GeoJSON properties.weight exactly"
            if require_stored_weight
            else "properties.weight; legacy positive cost or node distance fallback"
        ),
        "nodes": sorted(points),
        "node_coordinates": [
            {"id": node, "x": points[node][0], "y": points[node][1]}
            for node in sorted(points)
        ],
        "edges": [
            {"from": start, "to": end, "weight": weight}
            for (start, end), weight in sorted(edge_weights.items())
        ],
    }


def build_compact_adjacency_graph(
    graph: dict,
    source_graph: str,
    *,
    require_stored_weight: bool = False,
) -> dict:
    """Build the coordinate-free adjacency format used by V2 experiments."""
    points, edges = build_route_inputs(
        graph, require_stored_weight=require_stored_weight
    )
    edge_weights = build_edge_weight_lookup(points, edges)
    adjacency: dict[str, list[dict[str, int | float]]] = {
        str(node): [] for node in sorted(points)
    }
    for (start, end), weight in sorted(edge_weights.items()):
        adjacency[str(start)].append({"to": end, "weight": weight})
    return {
        "type": "CompactAdjacencyGraph",
        "source_graph": source_graph,
        "directed": True,
        "weight_rule": (
            "GeoJSON properties.weight exactly"
            if require_stored_weight
            else "properties.weight; legacy positive cost or node distance fallback"
        ),
        "nodes": sorted(points),
        "adjacency": adjacency,
    }


def compact_graph_edges(graph: dict[str, Any]) -> list[dict[str, int | float]]:
    """Normalize CompactRouteGraph or CompactAdjacencyGraph edges."""
    graph_type = graph.get("type")
    if graph_type == "CompactAdjacencyGraph":
        records: list[dict[str, int | float]] = []
        adjacency = graph.get("adjacency")
        if not isinstance(adjacency, dict):
            raise ValueError("CompactAdjacencyGraph.adjacency는 객체여야 합니다.")
        for raw_start, neighbors in adjacency.items():
            if not isinstance(neighbors, list):
                raise ValueError("CompactAdjacencyGraph의 인접 목록은 배열이어야 합니다.")
            start = int(raw_start)
            for neighbor in neighbors:
                if not isinstance(neighbor, dict):
                    raise ValueError("CompactAdjacencyGraph의 인접 항목은 객체여야 합니다.")
                records.append(
                    {
                        "from": start,
                        "to": int(neighbor["to"]),
                        "weight": float(neighbor["weight"]),
                    }
                )
        return records
    if graph_type == "CompactRouteGraph":
        return [
            {
                "from": int(edge["from"]),
                "to": int(edge["to"]),
                "weight": float(edge["weight"]),
            }
            for edge in graph.get("edges", [])
        ]
    raise ValueError(f"지원하지 않는 compact graph type: {graph_type!r}")



def get_available_edges(
    graph: dict[str, Any],
    current_node: int,
    *,
    visited_nodes: list[int] | set[int] | None = None,
) -> list[dict[str, int | float]]:
    """Return exact unvisited outgoing edges for one node.

    Node/Edge IDs are structured data, so V2 iterative routing uses an exact
    adjacency lookup instead of vector-similarity retrieval.  The returned
    distance is the stored directed edge weight; it is not recalculated.
    """
    nodes = {int(node) for node in graph.get("nodes", [])}
    current_node = int(current_node)
    if current_node not in nodes:
        raise ValueError(f"현재 노드가 graph에 없습니다: {current_node}")

    visited = {int(node) for node in (visited_nodes or [])}
    available = [
        {"node": int(edge["to"]), "distance": float(edge["weight"])}
        for edge in compact_graph_edges(graph)
        if int(edge["from"]) == current_node
        and int(edge["to"]) not in visited
    ]
    return sorted(available, key=lambda item: (item["node"], item["distance"]))


def build_edge_weight_lookup(
    points: dict[int, tuple[float, float]],
    edges: list[tuple[int, int, float]],
) -> dict[tuple[int, int], float]:
    """Index already-resolved edge weights and keep the lightest parallel edge."""
    edge_weights: dict[tuple[int, int], float] = {}
    for start, end, weight in edges:
        if start not in points or end not in points:
            continue
        weight = float(weight)
        if not math.isfinite(weight) or weight < 0:
            raise ValueError("간선 weight는 0 이상의 유한한 숫자여야 합니다.")
        edge_key = (start, end)
        edge_weights[edge_key] = min(edge_weights.get(edge_key, math.inf), weight)
    return edge_weights


def validate_and_calculate_path_distance(
    points: dict[int, tuple[float, float]],
    edges: list[tuple[int, int, float]],
    path: list[int | str],
    start_id: int,
    target_id: int,
) -> tuple[list[int], float]:
    """Check nodes and directed edges, then sum the resolved stored weights."""
    if not isinstance(path, list) or not path:
        raise ValueError("경로가 비어 있거나 list 형식이 아닙니다.")

    normalized_path = [int(node_id) for node_id in path]
    if normalized_path[0] != start_id:
        raise ValueError(f"시작 노드 불일치: {normalized_path[0]} != {start_id}")
    if normalized_path[-1] != target_id:
        raise ValueError(f"도착 노드 불일치: {normalized_path[-1]} != {target_id}")
    for node_id in normalized_path:
        if node_id not in points:
            raise ValueError(f"존재하지 않는 노드입니다: {node_id}")

    edge_weights = build_edge_weight_lookup(points, edges)
    total_distance = 0.0
    for start, end in zip(normalized_path, normalized_path[1:]):
        edge_key = (start, end)
        if edge_key not in edge_weights:
            raise ValueError(f"존재하지 않는 방향성 edge입니다: {start} -> {end}")
        total_distance += edge_weights[edge_key]
    return normalized_path, total_distance


def compare_path_metrics(
    baseline_path: list[int],
    baseline_distance: float,
    llm_path: list[int],
    llm_distance: float,
) -> dict[str, bool | float]:
    """Compare locally calculated paths and distances."""
    return {
        "same_path": baseline_path == llm_path,
        "same_distance": math.isclose(
            baseline_distance,
            llm_distance,
            rel_tol=1e-9,
            abs_tol=1e-9,
        ),
        "distance_difference": llm_distance - baseline_distance,
    }
