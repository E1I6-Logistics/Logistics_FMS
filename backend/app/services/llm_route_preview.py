"""Read-only local-model route preview using the live Route Graph."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from ..config import ROUTE_GRAPH_PATH
from .route_model_catalog import enabled_model_configuration
from simulation.services.route_service import (
    build_compact_adjacency_graph,
    build_route_inputs,
    compare_path_metrics,
    plan_route,
    validate_and_calculate_path_distance,
)
from simulation.services.iterative_route_policy import (
    MAX_VISITS_PER_NODE, NEXT_NODE_INSTRUCTIONS, next_node_options, next_node_state,
)


def _validated_result(
    graph: dict[str, Any], path: list[int], start: int, target: int,
    model: str | None, calls: int,
) -> dict[str, Any]:
    """선택한 경로를 검증하고 코드 최단경로와 거리·노드 순서를 비교한다."""
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


def preview_llm_route(
    graph: dict[str, Any],
    start_node: str | int,
    target_node: str | int,
    *,
    selector: str = "ollama",
    model: str | None = None,
    provider: Any | None = None,
) -> dict[str, Any]:
    """시험과 같은 상태·후보 규칙으로 경로를 선택하고 유효성을 검사한다."""
    load_dotenv(
        Path(__file__).resolve().parents[3] / "simulation" / ".env",
        override=False,
    )
    if model is None:
        raise ValueError("경로 모델을 선택하세요.")
    model_config = enabled_model_configuration(selector, model)
    compact = build_compact_adjacency_graph(
        graph, ROUTE_GRAPH_PATH.name, require_stored_weight=True,
    )
    nodes = sorted(int(node) for node in compact["nodes"])
    start, target = int(start_node), int(target_node)
    if start not in nodes or target not in nodes:
        raise ValueError("출발 또는 목적지 노드가 현재 Route Graph에 없습니다.")
    if start == target:
        return _validated_result(graph, [start], start, target, model, 0)

    # The benchmark also uses one selector call per multi-candidate step.
    if selector == "ollama":
        from simulation.route_selector.ollama_selector import OllamaSelector
        if provider is None:
            from simulation.llm_providers.ollama_provider import OllamaPathProvider
            provider = OllamaPathProvider(
                model=model,
                host=model_config["host"],
                timeout_seconds=float(model_config["timeout_seconds"]),
                options=dict(model_config["options"]),
                keep_alive=str(model_config["keep_alive"]),
                think=model_config["think"],
            )
        decision_selector = OllamaSelector(provider)
    elif selector == "laya":
        from simulation.route_selector.laya_selector import LayaSelector
        decision_selector = LayaSelector(model=model)
    else:
        from simulation.route_selector.kev_selector import KevSelector
        decision_selector = KevSelector(model=model)

    step_limit = int(model_config.get("max_steps") or len(nodes) * 2)
    if step_limit < 1:
        raise ValueError("최대 이동 단계는 양수여야 합니다.")
    path = [start]
    used_edges: set[tuple[int, int]] = set()
    visit_counts = {start: 1}
    total_weight = 0.0
    model_calls = 0
    for step_index in range(step_limit):
        current = path[-1]
        options = next_node_options(
            compact, nodes, current, path, used_edges, visit_counts,
            candidate_scope="neighbors",
            max_visits_per_node=MAX_VISITS_PER_NODE,
        )
        candidate_nodes = options["candidate_nodes"]
        if not candidate_nodes:
            raise ValueError(
                f"순환 방지 조건을 만족하는 이동 후보가 없습니다: current={current}"
            )
        if len(candidate_nodes) == 1:
            # The choice APIs need at least two options, so the benchmark
            # records this as a deterministic step without a model call.
            selected = candidate_nodes[0]
        else:
            state = next_node_state(
                compact, current, target, path, used_edges, visit_counts,
                total_weight, options, context_mode="neighbor_context",
                max_visits_per_node=MAX_VISITS_PER_NODE,
            )
            candidates = {
                f"node_{node}": f"Node {node}" for node in candidate_nodes
            }
            model_calls += 1
            # 모델 입력 및 결과
            result = decision_selector.select_choice( 
                state, # 전체 그래프, 현재·목표 노드, 방문 기록, 누적 거리 등 현재 경로 상태
                candidates, # 이번 단계에서 선택 가능한 다음 노드 목록
                NEXT_NODE_INSTRUCTIONS, # 어떤 기준으로 노드를 선택할지 알려주는 지시문
                question_id=f"route_{start}_{target}_step_{step_index + 1}", # 이번 요청을 구분하는 ID
            )
            choice = str(result.get("choice", ""))
            if not choice.startswith("node_"):
                raise ValueError(f"잘못된 다음 노드 응답: {choice}")
            selected = int(choice.removeprefix("node_"))
        if selected not in candidate_nodes:
            raise ValueError(f"연결되지 않은 노드 선택: {current} -> {selected}")
        if (current, selected) in used_edges:
            raise ValueError(f"이미 사용한 방향성 edge 재선택: {current} -> {selected}")
        weight = next(
            float(edge["weight"])
            for edge in options["available_edges"]
            if int(edge["node"]) == selected
        )
        used_edges.add((current, selected))
        visit_counts[selected] = visit_counts.get(selected, 0) + 1
        total_weight += weight
        path.append(selected)
        if selected == target:
            return _validated_result(
                graph, path, start, target, model, model_calls
            )
    raise ValueError(
        f"최대 단계 초과: max_steps={step_limit}, "
        f"target={target}, current={path[-1]}"
    )
