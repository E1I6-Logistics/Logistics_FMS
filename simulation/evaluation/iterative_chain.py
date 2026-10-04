"""Iterative next-node selection experiment for route generation.

The model receives the complete graph and the current navigation state on every
step.  In the RAG condition, the request additionally contains the current
node's direct connections and stored edge distances.  Python never preselects a
candidate for the model; it only validates the returned node after inference.
"""

from __future__ import annotations

import copy
import math
from typing import Any


ITERATIVE_STEP_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "selected_node": {"type": "integer"},
    },
    "required": ["selected_node"],
}


def _request_characters(inference: dict[str, Any]) -> int:
    request = inference.get("request") or {}
    return sum(
        len(str(message.get("content", "")))
        for message in request.get("messages", [])
    )


def _build_outgoing(
    graph: dict[str, Any], nodes: set[int]
) -> dict[int, list[tuple[int, float]]]:
    outgoing: dict[int, list[tuple[int, float]]] = {node: [] for node in nodes}
    seen_pairs: set[tuple[int, int]] = set()

    for edge in graph.get("edges", []):
        start = int(edge["from"])
        end = int(edge["to"])
        weight = float(edge.get("weight", edge.get("distance")))
        if start not in nodes or end not in nodes:
            raise ValueError("Compact Graph edge가 존재하지 않는 node를 참조합니다.")
        if weight < 0 or not math.isfinite(weight):
            raise ValueError("Compact Graph에 잘못된 edge distance가 있습니다.")
        if (start, end) in seen_pairs:
            raise ValueError(f"중복 directed edge입니다: {start} -> {end}")
        seen_pairs.add((start, end))
        outgoing[start].append((end, weight))

    for edges in outgoing.values():
        edges.sort(key=lambda item: (item[0], item[1]))
    return outgoing


def _rag_context(
    current_node: int,
    outgoing: dict[int, list[tuple[int, float]]],
) -> dict[str, Any]:
    """Return facts only: direct connections and stored distances for one node."""
    return {
        "node": current_node,
        "connections": [
            {"node": neighbor, "distance": distance}
            for neighbor, distance in outgoing.get(current_node, [])
        ],
    }


def run_iterative_chain(
    provider: Any,
    graph: dict[str, Any],
    start_id: int,
    target_id: int,
    *,
    instructions: str,
    max_steps: int,
    rag_enabled: bool = False,
) -> dict[str, Any]:
    """Ask the model for exactly one next node per API call until target arrival.

    Input per step:
      - route_graph: complete graph
      - current_node
      - target_node
      - visited_nodes
      - accumulated_distance
      - rag_context (RAG condition only): current node direct connections

    The model is not given a separately computed criteria/candidate list.  After
    the model responds, Python validates that the selected node is connected by
    a real outgoing edge from the current node, rejects loops, accumulates the
    stored edge distance, and advances the state by one node.
    """
    nodes = {int(node) for node in graph.get("nodes", [])}
    if start_id not in nodes or target_id not in nodes:
        raise ValueError("start_node 또는 target_node가 graph에 없습니다.")
    if max_steps < 1:
        raise ValueError("max_steps는 1 이상이어야 합니다.")

    outgoing = _build_outgoing(graph, nodes)

    current_node = start_id
    visited_nodes = [start_id]
    accumulated_distance = 0.0
    chain_steps: list[dict[str, Any]] = []
    inferences: list[dict[str, Any]] = []
    provider.last_chain_inferences = inferences
    provider.last_chain_steps = chain_steps

    if start_id == target_id:
        return {
            "path": visited_nodes,
            "reported_total_distance": 0.0,
            "chain_steps": chain_steps,
            "api_call_count": 0,
            "request_character_count": 0,
        }

    for step_number in range(1, max_steps + 1):
        direct_connections = outgoing.get(current_node, [])
        if not direct_connections:
            raise ValueError(
                f"현재 노드 {current_node}에서 이동 가능한 outgoing edge가 없습니다."
            )

        payload: dict[str, Any] = {
            "route_graph": graph,
            "current_node": current_node,
            "target_node": target_id,
            "visited_nodes": list(visited_nodes),
            "accumulated_distance": accumulated_distance,
        }
        context = None
        if rag_enabled:
            context = _rag_context(current_node, outgoing)
            payload["rag_context"] = context

        # 후보가 하나뿐이어도 API를 호출한다.  그래프 이해와 인접성 판단 자체가
        # Iterative 실험의 평가 대상이기 때문이다.
        action = provider.request_structured(
            instructions=instructions,
            payload=payload,
            output_schema=ITERATIVE_STEP_SCHEMA,
        )
        inference = copy.deepcopy(getattr(provider, "last_inference", None))
        if inference is not None:
            inferences.append(inference)

        selected_node = int(action["selected_node"])
        edge_distance = next(
            (
                distance
                for neighbor, distance in direct_connections
                if neighbor == selected_node
            ),
            None,
        )
        if edge_distance is None:
            raise ValueError(
                "모델이 현재 노드와 직접 연결되지 않은 노드를 선택했습니다: "
                f"{current_node} -> {selected_node}"
            )
        if selected_node in visited_nodes:
            raise ValueError(
                f"모델이 이미 방문한 노드를 다시 선택했습니다: {selected_node}"
            )

        accumulated_distance += edge_distance
        previous_node = current_node
        current_node = selected_node
        visited_nodes.append(current_node)

        step_result: dict[str, Any] = {
            "step": step_number,
            "current_node": previous_node,
            "selected_node": selected_node,
            "edge_distance": edge_distance,
            "accumulated_distance": accumulated_distance,
        }
        if context is not None:
            step_result["rag_context"] = context
        chain_steps.append(step_result)

        if current_node == target_id:
            return {
                "path": list(visited_nodes),
                "reported_total_distance": accumulated_distance,
                "chain_steps": chain_steps,
                "api_call_count": len(chain_steps),
                "request_character_count": sum(
                    _request_characters(item) for item in inferences
                ),
            }

    raise RuntimeError(
        f"Iterative Chain이 max_steps={max_steps} 안에 target_node에 도착하지 못했습니다."
    )
