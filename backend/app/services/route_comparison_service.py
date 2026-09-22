"""Pure route checks shared by the LLM experiment and feature tests.

This module does not start robots, call a model, or write result files.
"""

from __future__ import annotations

import math


def build_edge_weight_lookup(
    points: dict[int, tuple[float, float]],
    edges: list[tuple[int, int, float]],
) -> dict[tuple[int, int], float]:
    """Use a positive edge cost, or the Euclidean distance for zero cost."""
    edge_weights: dict[tuple[int, int], float] = {}
    
    for start, end, cost in edges:
        if start not in points or end not in points:
            continue
        weight = cost if cost > 0 else math.dist(points[start], points[end])
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
    """Check nodes and directed edges, then calculate distance locally."""
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
            baseline_distance, llm_distance, rel_tol=1e-9, abs_tol=1e-9
        ),
        "distance_difference": llm_distance - baseline_distance,
    }
