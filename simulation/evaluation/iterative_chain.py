"""V2 adapter using the same neighbor-choice runner as the final 84-pair test."""
from __future__ import annotations

import copy
from typing import Any

from simulation.route_selector.ollama_selector import OllamaSelector
from simulation.services.iterative_route_runner import run_selected_route
from simulation.services.route_service import compact_graph_edges, build_edge_weight_lookup

# 실제 요청은 OllamaSelector가 현재 후보 ID를 enum으로 제한한 choice 스키마를 만든다.
ITERATIVE_STEP_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "properties": {"choice": {"type": "string"}}, "required": ["choice"],
}


class IterativeRouteError(RuntimeError):
    """Retain failed steps and the partial path for benchmark diagnostics."""
    def __init__(self, message: str, answer: dict[str, Any]):
        super().__init__(message)
        self.route_answer = answer


class _RecordingSelector(OllamaSelector):
    # 최종 시험의 OllamaSelector를 그대로 호출하고 성공·실패 요청을 함께 보관한다.
    def __init__(self, provider: Any, inferences: list[dict[str, Any]]):
        super().__init__(provider)
        self.inferences = inferences

    def select_choice(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        self.provider.last_inference = None
        try:
            return super().select_choice(*args, **kwargs)
        finally:
            inference = copy.deepcopy(getattr(self.provider, "last_inference", None))
            if inference is not None:
                self.inferences.append(inference)


def run_iterative_chain(
    provider: Any, graph: dict[str, Any], start_id: int, target_id: int, *,
    instructions: str, max_steps: int, neighbor_context_enabled: bool = False,
    route_inputs: dict[str, Any] | None = None, baseline_case: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Run neighbor-only choices, limited revisits and forced steps via the shared runner."""
    nodes = sorted(int(node) for node in graph.get("nodes", []))
    if start_id not in nodes or target_id not in nodes:
        raise ValueError("start_node 또는 target_node가 graph에 없습니다.")
    if route_inputs is None:
        # 단독 검증에서는 좌표가 필요 없다. None 값은 노드 존재 확인에만 사용한다.
        points = {node: None for node in nodes}
        edges = [(int(e["from"]), int(e["to"]), float(e["weight"]))
                 for e in compact_graph_edges(graph)]
    else:
        points, edges = route_inputs["points"], route_inputs["edges"]
    prepared = {"compact_graph": graph, "nodes": nodes, "points": points,
                "edges": edges, "edge_weights": build_edge_weight_lookup(points, edges)}
    case = {"start": start_id, "target": target_id, **(baseline_case or {})}
    inferences: list[dict[str, Any]] = []
    provider.last_inference = None
    provider.last_chain_inferences = inferences
    provider.last_chain_steps = []
    provider.last_chain_result = None
    selector = _RecordingSelector(provider, inferences)
    result = run_selected_route(
        selector, prepared, case, "neighbors", 0.15,
        "neighbor_context" if neighbor_context_enabled else "full_graph_only",
        max_steps, instructions=instructions,
    )
    provider.last_chain_steps = result["steps"]
    provider.last_chain_result = result
    answer = {
        "path": result["path"], "reported_total_distance": result["recalculated_distance"],
        "chain_steps": result["steps"], "api_call_count": result["api_call_count"],
        "request_character_count": sum(
            len(str(m.get("content", "")))
            for item in inferences for m in (item.get("request") or {}).get("messages", [])
        ),
    }
    if result["error"]:
        raise IterativeRouteError(result["error"], answer)
    return answer
