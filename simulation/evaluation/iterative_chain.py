"""Model-driven iterative Dijkstra experiment.

Python stores and validates state only.  It never substitutes a node choice or
relaxation when the model returns an invalid action.
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
        "selected_distance": {"type": "number"},
        "relaxations": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "node": {"type": "integer"},
                    "distance": {"type": "number"},
                    "predecessor": {"type": "integer"},
                },
                "required": ["node", "distance", "predecessor"],
            },
        },
        "finished": {"type": "boolean"},
    },
    "required": [
        "selected_node",
        "selected_distance",
        "relaxations",
        "finished",
    ],
}


def _close(left: float, right: float) -> bool:
    return math.isclose(left, right, rel_tol=1e-9, abs_tol=1e-9)


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
) -> dict[str, Any]:
    """Run validated model-selected Dijkstra steps until target settlement."""
    nodes = {int(node) for node in graph.get("nodes", [])}
    if start_id not in nodes or target_id not in nodes:
        raise ValueError("start_node 또는 target_node가 graph에 없습니다.")

    outgoing: dict[int, list[tuple[int, float]]] = {node: [] for node in nodes}
    for edge in graph.get("edges", []):
        start, end = int(edge["from"]), int(edge["to"])
        weight = float(edge["weight"])
        if start not in nodes or end not in nodes or weight < 0 or not math.isfinite(weight):
            raise ValueError("Compact Graph에 잘못된 edge가 있습니다.")
        outgoing[start].append((end, weight))

    tentative = {start_id: 0.0}
    predecessor: dict[int, int] = {}
    settled: list[int] = []
    chain_steps: list[dict[str, Any]] = []
    inferences: list[dict[str, Any]] = []
    provider.last_chain_inferences = inferences
    provider.last_chain_steps = chain_steps

    for step_number in range(1, max_steps + 1):
        reachable = {
            node: distance
            for node, distance in tentative.items()
            if node not in settled
        }
        if not reachable:
            raise ValueError("모델 탐색 상태에서 도착 노드에 도달할 수 없습니다.")

        payload = {
            "route_graph": graph,
            "start_node": start_id,
            "target_node": target_id,
            "search_state": {
                "step": step_number,
                "settled_nodes": settled,
                "tentative_distances": [
                    {
                        "node": node,
                        "distance": distance,
                        "predecessor": predecessor.get(node),
                    }
                    for node, distance in sorted(reachable.items())
                ],
                "unvisited_node_ids": sorted(nodes.difference(settled)),
            },
        }
        action = provider.request_structured(
            instructions=instructions,
            payload=payload,
            output_schema=ITERATIVE_STEP_SCHEMA,
        )
        inference = copy.deepcopy(getattr(provider, "last_inference", None))
        if inference is not None:
            inferences.append(inference)

        selected = int(action["selected_node"])
        selected_distance = float(action["selected_distance"])
        if selected not in reachable:
            raise ValueError(f"선택할 수 없는 노드입니다: {selected}")
        minimum = min(reachable.values())
        if not _close(reachable[selected], minimum):
            raise ValueError(
                f"모델이 최소 tentative distance 노드를 선택하지 않았습니다: {selected}"
            )
        if not _close(selected_distance, reachable[selected]):
            raise ValueError(f"selected_distance가 상태와 다릅니다: {selected}")

        is_target = selected == target_id
        if bool(action["finished"]) != is_target:
            raise ValueError("finished 값과 target_node 확정 상태가 다릅니다.")

        expected: dict[int, tuple[float, int]] = {}
        if not is_target:
            for neighbor, weight in outgoing[selected]:
                if neighbor in settled:
                    continue
                candidate = selected_distance + weight
                if candidate < tentative.get(neighbor, math.inf):
                    previous = expected.get(neighbor)
                    if previous is None or candidate < previous[0]:
                        expected[neighbor] = (candidate, selected)

        returned: dict[int, tuple[float, int]] = {}
        for update in action["relaxations"]:
            node = int(update["node"])
            if node in returned:
                raise ValueError(f"중복 relaxation입니다: {node}")
            returned[node] = (
                float(update["distance"]),
                int(update["predecessor"]),
            )
        if set(returned) != set(expected):
            raise ValueError(
                "모델 relaxation 대상이 실제 개선 가능한 outgoing edge와 다릅니다: "
                f"expected={sorted(expected)}, returned={sorted(returned)}"
            )
        for node, (distance, parent) in returned.items():
            expected_distance, expected_parent = expected[node]
            if parent != expected_parent or not _close(distance, expected_distance):
                raise ValueError(f"잘못된 relaxation 값입니다: {selected} -> {node}")

        settled.append(selected)
        for node, (distance, parent) in returned.items():
            tentative[node] = distance
            predecessor[node] = parent
        chain_steps.append({"step": step_number, **action})

        if is_target:
            path = [target_id]
            while path[-1] != start_id:
                if path[-1] not in predecessor:
                    raise ValueError("모델 상태에서 최종 경로를 복원할 수 없습니다.")
                path.append(predecessor[path[-1]])
                if len(path) > len(nodes):
                    raise ValueError("모델 predecessor에 순환이 있습니다.")
            path.reverse()
            return {
                "path": path,
                "reported_total_distance": selected_distance,
                "chain_steps": chain_steps,
                "api_call_count": len(chain_steps),
                "request_character_count": sum(
                    _request_characters(item) for item in inferences
                ),
            }

    raise RuntimeError(f"Iterative Chain이 max_steps={max_steps} 안에 끝나지 않았습니다.")
