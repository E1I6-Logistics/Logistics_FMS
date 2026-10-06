"""Model-driven iterative next-node route experiment.

Every step sends the full graph and current route state.  The neighbor-context
condition adds exact outgoing edges looked up by current node ID.
Python does not create model-facing criteria or choose a node for the model;
it only validates that the returned node is connected by a directed edge.
"""

from __future__ import annotations

import copy
import math
from typing import Any

from simulation.services.route_service import (
    compact_graph_edges,
    get_available_edges,
)


ITERATIVE_STEP_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {"selected_node": {"type": "integer"}},
    "required": ["selected_node"],
}


def _request_characters(inference: dict[str, Any]) -> int:
    request = inference.get("request") or {}
    return sum(
        len(str(message.get("content", "")))
        for message in request.get("messages", [])
    )


def run_iterative_chain(
    provider: Any,
    graph: dict[str, Any],
    start_id: int,
    target_id: int,
    *,
    instructions: str,
    max_steps: int,
    neighbor_context_enabled: bool = False,
) -> dict[str, Any]:
    """Ask for one next node per API call until target or validation failure."""
    nodes = {int(node) for node in graph.get("nodes", [])}
    if start_id not in nodes or target_id not in nodes:
        raise ValueError("start_node 또는 target_node가 graph에 없습니다.")

    outgoing: dict[int, list[tuple[int, float]]] = {node: [] for node in nodes}
    for edge in compact_graph_edges(graph):
        start, end = int(edge["from"]), int(edge["to"])
        weight = float(edge["weight"])
        if (
            start not in nodes
            or end not in nodes
            or weight < 0
            or not math.isfinite(weight)
        ):
            raise ValueError("Compact Graph에 잘못된 edge가 있습니다.")
        outgoing[start].append((end, weight))
    for edges in outgoing.values():
        edges.sort(key=lambda item: (item[0], item[1]))

    current = start_id
    path = [start_id]
    accumulated_distance = 0.0
    chain_steps: list[dict[str, Any]] = []
    inferences: list[dict[str, Any]] = []
    provider.last_chain_inferences = inferences
    provider.last_chain_steps = chain_steps

    if start_id == target_id:
        return {
            "path": path,
            "reported_total_distance": 0.0,
            "chain_steps": chain_steps,
            "api_call_count": 0,
            "request_character_count": 0,
        }

    for step_number in range(1, max_steps + 1):
        state: dict[str, Any] = {
            "route_graph": graph,
            "current_node": current,
            "target_node": target_id,
            "visited_nodes": list(path),
            "accumulated_distance": accumulated_distance,
        }
        if neighbor_context_enabled:
            # Node/Edge는 ID가 명확한 구조화 데이터이므로 벡터 유사도 검색을
            # 사용하지 않고 adjacency에서 현재 Node의 Edge를 정확히 조회한다.
            state["available_edges"] = get_available_edges(
                graph,
                current,
                visited_nodes=path,
            )
            if not state["available_edges"]:
                raise ValueError(f"이동 가능한 미방문 edge가 없습니다: {current}")

        action = provider.request_structured(
            instructions=instructions,
            payload=state,
            output_schema=ITERATIVE_STEP_SCHEMA,
        )
        inference = copy.deepcopy(getattr(provider, "last_inference", None))
        if inference is not None:
            inferences.append(inference)

        selected = int(action["selected_node"])
        if selected in path:
            raise ValueError(f"이미 방문한 노드 재선택: {selected}")
        direct_weights = {node: weight for node, weight in outgoing[current]}
        if selected not in direct_weights:
            raise ValueError(
                f"존재하지 않는 방향성 edge: {current} -> {selected}"
            )

        previous = current
        weight = direct_weights[selected]
        current = selected
        path.append(current)
        accumulated_distance += weight
        chain_steps.append(
            {
                "step": step_number,
                "current_node": previous,
                "target_node": target_id,
                "selected_node": selected,
                "edge_weight": weight,
                "accumulated_distance": accumulated_distance,
                "visited_nodes": list(path),
                "neighbor_context_enabled": neighbor_context_enabled,
                "available_edges": state.get("available_edges"),
                "reached_target": current == target_id,
            }
        )

        if current == target_id:
            return {
                "path": path,
                "reported_total_distance": accumulated_distance,
                "chain_steps": chain_steps,
                "api_call_count": len(chain_steps),
                "request_character_count": sum(
                    _request_characters(item) for item in inferences
                ),
            }

    raise RuntimeError(
        f"Iterative next-node가 max_steps={max_steps} 안에 Target에 도달하지 못했습니다."
    )
