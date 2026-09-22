"""Directed shortest paths using the same edge cost rule as mock_fleet."""

from __future__ import annotations

import heapq
import math
from typing import Any

from .route_graph import load_route_graph, node_lookup


def plan_route(start_id: str, goal_id: str, graph: dict[str, Any] | None = None) -> dict[str, Any]:
    graph = graph if graph is not None else load_route_graph()
    nodes = node_lookup(graph)

    start_id, goal_id = str(start_id), str(goal_id)
    if start_id not in nodes or goal_id not in nodes:

        raise ValueError(f"존재하지 않는 경로 노드: {start_id} → {goal_id}")
    points = {key: tuple(map(float, node["geometry"]["coordinates"][:2])) for key, node in nodes.items()}
    adjacency: dict[str, list[tuple[str, float, str]]] = {key: [] for key in nodes}

    for feature in graph.get("features", []):
        props = feature.get("properties") or {}
        if props.get("startid") is None or props.get("endid") is None:
            continue

        start, end = str(props["startid"]), str(props["endid"])
        if start not in points or end not in points:
            continue

        cost = float(props.get("cost", 0))
        if not math.isfinite(cost):
            raise ValueError("간선 비용은 유한한 숫자여야 합니다.")

        weight = cost if cost > 0 else math.dist(points[start], points[end])
        edge_id = str(props.get("id", f"{start}-{end}"))
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
