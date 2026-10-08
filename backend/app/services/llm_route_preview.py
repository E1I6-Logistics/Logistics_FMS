"""Read-only local-model route preview using the live Route Graph."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from simulation.llm_providers.ollama_provider import OllamaPathProvider
from simulation.route_selector.kev_selector import KevSelector
from simulation.route_selector.laya_selector import LayaSelector
from .route_model_catalog import require_enabled_model
from simulation.services.route_service import (
    build_compact_adjacency_graph,
    build_route_inputs,
    compare_path_metrics,
    get_available_edges,
    plan_route,
    validate_and_calculate_path_distance,
)

load_dotenv(Path(__file__).resolve().parents[3] / "simulation" / ".env", override=False)

def _validated_result(
    graph: dict[str, Any], path: list[int], start: int, target: int,
    model: str | None, calls: int,
) -> dict[str, Any]:
    """Recalculate model cost and compare against deterministic ground truth."""
    points, edges = build_route_inputs(graph, require_stored_weight=True)
    checked_path, distance = validate_and_calculate_path_distance(
        points, edges, path, start, target
    )
    baseline = plan_route(
        str(start), str(target), graph, require_stored_weight=True
    )
    metrics = compare_path_metrics(
        [int(node) for node in baseline["node_ids"]],
        float(baseline["cost"]),
        checked_path,
        distance,
    )
    return {
        "path": [str(node) for node in checked_path],
        "model": model,
        "total_weight": distance,
        "calls": calls,
        "baseline_path": [str(node) for node in baseline["node_ids"]],
        "baseline_weight": float(baseline["cost"]),
        **metrics,
    }


NEXT_NODE_INSTRUCTIONS = (
    "Choose exactly one next node on a directed route from current_node to "
    "target_node. Use route_graph adjacency and stored edge weights to prefer "
    "the lowest total remaining cost, not merely the cheapest immediate edge. "
    "The answer MUST be a node in available_edges. Never select a visited node. "
    "occupied_nodes describes current robot positions, not permanently closed "
    "nodes; the reservation and yield controller will decide when traversal is safe. "
    "Return only the selected next node in the required response format."
)


def _can_reach_target(
    compact: dict[str, Any], source: int, target: int, forbidden: set[int],
) -> bool:
    """Check directed reachability only; do not rank routes or choose a node."""
    pending = [source]
    seen = set(forbidden)
    while pending:
        node = pending.pop()
        if node == target:
            return True
        if node in seen:
            continue
        seen.add(node)
        pending.extend(
            int(edge["to"]) for edge in compact["adjacency"].get(str(node), [])
            if int(edge["to"]) not in seen
        )
    return False


def preview_llm_route(
    graph: dict[str, Any],
    start_node: str | int,
    target_node: str | int,
    *,
    selector: str = "ollama",
    model: str | None = None,
    provider: OllamaPathProvider | None = None,
    occupied_nodes: set[int] | set[str] | None = None,
) -> dict[str, Any]:
    """Let the selected model choose adjacent nodes; reject invalid paths."""
    if model is None:
        raise ValueError("경로 모델을 선택하세요.")
    require_enabled_model(selector, model)
    compact = build_compact_adjacency_graph(
        graph,
        os.getenv("FMS_ROUTE_GRAPH", "test.geojson"),
        require_stored_weight=True,
    )
    nodes = {int(node) for node in compact["nodes"]}
    start, target = int(start_node), int(target_node)
    if start not in nodes or target not in nodes:
        raise ValueError("출발 또는 목적지 노드가 현재 Route Graph에 없습니다.")
    occupied = {int(node) for node in (occupied_nodes or set())} & nodes
    occupied.discard(start)
    if start == target:
        return _validated_result(graph, [start], start, target, model, 0)
    # Physical occupancy is temporary. The TrafficManager decides whether a
    # blocker should yield or this robot should wait before entering an edge.
    if not _can_reach_target(compact, start, target, set()):
        raise ValueError("현재 지도에서 목적지까지 연결된 경로가 없습니다.")

    if selector == "ollama" and provider is None:
        provider = OllamaPathProvider(model=model, options={
            "temperature": 0,
            "seed": 20260928,
            "num_ctx": int(os.getenv("LLM_NAV_NUM_CTX", "8192")),
            "num_predict": int(os.getenv("LLM_NAV_NUM_PREDICT", "128")),
        })
    decision_selector = (
        LayaSelector(model=model) if selector == "laya" else
        KevSelector(model=model) if selector == "kev" else None
    )
    path = [start]
    total_weight = 0.0
    for _ in range(len(nodes) - 1):
        current = path[-1]
        available = [
            edge for edge in get_available_edges(compact, current, visited_nodes=path)
            if _can_reach_target(
                compact, int(edge["node"]), target, set(path),
            )
        ]
        if not available:
            raise ValueError(
                f"노드 {current}에서 기방문 노드를 제외하면 "
                "목적지까지 갈 수 있는 다음 노드가 없습니다."
            )
        choices = {int(edge["node"]): float(edge["weight"]) for edge in available}
        state = {
            "route_graph": compact,
            "current_node": current,
            "target_node": target,
            "visited_nodes": path,
            "accumulated_distance": total_weight,
            "available_edges": available,
            "occupied_nodes": sorted(occupied),
        }
        if decision_selector is not None:
            # Choice APIs require at least two options; one outgoing edge is
            # deterministic and needs no model request.
            if len(choices) == 1:
                selected = next(iter(choices))
            else:
                result = decision_selector.select_choice(
                    state,
                    {f"node_{node}": f"Node {node}" for node in sorted(choices)},
                    NEXT_NODE_INSTRUCTIONS,
                    question_id=f"route_{start}_{target}_step_{len(path)}",
                )
                choice = str(result.get("choice", ""))
                if not choice.startswith("node_"):
                    raise ValueError(f"잘못된 다음 노드 응답: {choice}")
                selected = int(choice.removeprefix("node_"))
        else:
            assert provider is not None
            response = provider.request_structured(
                instructions=NEXT_NODE_INSTRUCTIONS,
                payload=state,
                output_schema={
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "selected_node": {"type": "integer", "enum": sorted(choices)},
                    },
                    "required": ["selected_node"],
                },
            )
            selected = response.get("selected_node")
        if isinstance(selected, bool) or not isinstance(selected, int):
            raise ValueError("LLM이 정수형 다음 노드 ID를 반환하지 않았습니다.")
        if selected not in choices:
            raise ValueError(f"LLM이 연결되지 않은 노드를 선택했습니다: {current} -> {selected}")
        path.append(selected)
        total_weight += choices[selected]
        if selected == target:
            return _validated_result(
                graph, path, start, target, model, len(path) - 1
            )
    raise ValueError("LLM 경로가 최대 단계 안에 목적지에 도착하지 못했습니다.")
