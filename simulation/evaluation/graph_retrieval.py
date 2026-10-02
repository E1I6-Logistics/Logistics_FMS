"""Retrieve the directed subgraph that can participate in a start-to-target path.

The retriever never computes or returns a shortest path.  It intersects nodes
reachable from the start with nodes that can reach the target, then exposes
their stored outgoing edge weights as an adjacency index for the model.
"""

from __future__ import annotations

import copy
from collections import deque
from typing import Any


def _reachable(seed: int, adjacency: dict[int, list[int]]) -> set[int]:
    visited = {seed}
    queue = deque([seed])
    while queue:
        node = queue.popleft()
        for neighbor in adjacency.get(node, []):
            if neighbor not in visited:
                visited.add(neighbor)
                queue.append(neighbor)
    return visited


def retrieve_path_relevant_graph(
    graph: dict[str, Any], start_id: int, target_id: int
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Return all nodes/edges on any possible directed start-to-target route."""
    nodes = {int(node) for node in graph.get("nodes", [])}
    if start_id not in nodes or target_id not in nodes:
        raise ValueError("retrieval start_node 또는 target_node가 graph에 없습니다.")

    forward = {node: [] for node in nodes}
    reverse = {node: [] for node in nodes}
    normalized_edges = []
    for edge in graph.get("edges", []):
        start, end = int(edge["from"]), int(edge["to"])
        weight = float(edge["weight"])
        if start not in nodes or end not in nodes:
            raise ValueError("retrieval graph edge가 존재하지 않는 node를 참조합니다.")
        forward[start].append(end)
        reverse[end].append(start)
        normalized_edges.append({"from": start, "to": end, "weight": weight})

    reachable_from_start = _reachable(start_id, forward)
    if target_id not in reachable_from_start:
        raise ValueError(f"{start_id}에서 {target_id}까지 연결된 경로가 없습니다.")
    can_reach_target = _reachable(target_id, reverse)
    relevant_nodes = reachable_from_start.intersection(can_reach_target)
    relevant_edges = [
        edge
        for edge in normalized_edges
        if edge["from"] in relevant_nodes and edge["to"] in relevant_nodes
    ]

    adjacency_index = []
    for node in sorted(relevant_nodes):
        neighbors = sorted(
            (
                {"node": edge["to"], "distance": edge["weight"]}
                for edge in relevant_edges
                if edge["from"] == node
            ),
            key=lambda item: (item["node"], item["distance"]),
        )
        adjacency_index.append({"node": node, "neighbors": neighbors})

    metadata = {
        "enabled": True,
        "policy": "forward_reachable_intersection_reverse_reachable",
        "description": (
            "All nodes reachable from start that can also reach target; "
            "no shortest path is calculated during retrieval."
        ),
        "source_node_count": len(nodes),
        "source_edge_count": len(normalized_edges),
        "retrieved_node_count": len(relevant_nodes),
        "retrieved_edge_count": len(relevant_edges),
    }
    retrieved = {
        "type": "CompactRouteGraph",
        "source_graph": graph.get("source_graph"),
        "directed": True,
        "weight_rule": graph.get("weight_rule"),
        "nodes": sorted(relevant_nodes),
        "node_coordinates": [
            item
            for item in graph.get("node_coordinates", [])
            if int(item["id"]) in relevant_nodes
        ],
        "edges": relevant_edges,
        "adjacency": adjacency_index,
        "retrieval": metadata,
    }
    return retrieved, copy.deepcopy(metadata)


def full_graph_metadata(graph: dict[str, Any]) -> dict[str, Any]:
    """Describe the no-retrieval condition with the same result fields."""
    return {
        "enabled": False,
        "policy": "full_graph",
        "source_node_count": len(graph.get("nodes", [])),
        "source_edge_count": len(graph.get("edges", [])),
        "retrieved_node_count": len(graph.get("nodes", [])),
        "retrieved_edge_count": len(graph.get("edges", [])),
    }


def ground_truth_coverage(
    retrieved_graph: dict[str, Any], expected_path: list[int]
) -> dict[str, Any]:
    """Measure retrieval recall after ground truth is known; never feed it to the model."""
    nodes = {int(node) for node in retrieved_graph.get("nodes", [])}
    edges = {
        (int(edge["from"]), int(edge["to"]))
        for edge in retrieved_graph.get("edges", [])
    }
    path_nodes = {int(node) for node in expected_path}
    path_edges = set(zip(expected_path, expected_path[1:]))
    return {
        "ground_truth_node_recall": (
            len(path_nodes.intersection(nodes)) / len(path_nodes) if path_nodes else 1.0
        ),
        "ground_truth_edge_recall": (
            len(path_edges.intersection(edges)) / len(path_edges) if path_edges else 1.0
        ),
        "ground_truth_path_available": path_nodes.issubset(nodes)
        and path_edges.issubset(edges),
    }
