"""Shared next-node input and cycle policy for benchmarks and live previews."""

from __future__ import annotations

from typing import Any

from .route_service import get_available_edges


# 모델 지시문 해석:
# 현재 노드에서 목적지까지 총 가중치가 가장 작은 유향 경로의 다음 노드 하나를 고른다.
# 바로 앞 간선의 가중치뿐 아니라 목적지까지 남은 비용을 고려하고, 저장된 가중치를 사용한다.
# 현재 노드에서 연결된 간선과 criteria에 있는 후보만 선택한다. available_edges가
# 있으면 그 목록에 있는 노드만 고른다. 사용한 간선은 다시 쓰지 않는다.
# 노드별 방문 상한을 지키며, backtrack_allowed일 때만 직전 노드로 돌아간다.
# 그보다 이전에 방문한 노드는 상한 내에서 재방문할 수 있다. 결과는 criteria ID만 반환한다.
NEXT_NODE_INSTRUCTIONS = (
    "Select exactly one next node for the minimum-total-weight directed route "
    "from current_node to target_node. Consider the estimated total remaining "
    "cost to the target, not merely the weight of the next edge. Use "
    "CompactAdjacencyGraph weights exactly as stored. The selected node must "
    "be connected by one directed edge from current_node and must be one of "
    "the supplied criteria. If available_edges is present, choose only a node "
    "listed there; it contains the exact outgoing edges and stored weights. "
    "Never reuse an edge in used_edges. Respect max_visits_per_node. Do not "
    "return to previous_node unless backtrack_allowed is true. Older nodes "
    "may be revisited within those limits. Return only the selected criteria ID."
)

MAX_VISITS_PER_NODE = 2

# 다음 노드 후보를 만들고, 직전 노드로 되돌아갈 수 있는지 결정
def next_node_options(
    compact_graph: dict[str, Any],
    nodes: list[int],
    current: int,
    path: list[int],
    used_edges: set[tuple[int, int]],
    visit_counts: dict[int, int],
    *,
    candidate_scope: str = "neighbors",
    max_visits_per_node: int = MAX_VISITS_PER_NODE,
) -> dict[str, Any]:
    """
    이미 사용한 방향성 간선·방문 상한을 넘는 노드는 제외한다. 
    직전 노드는 다른 후보가 없을 때만 허용한다. 
    neighbors는 연결 노드만, all은 전체 노드를 후보로 둔다.
    """
    if candidate_scope not in {"neighbors", "all"}:
        raise ValueError(f"Unsupported candidate_scope: {candidate_scope}")
    
    previous_node = path[-2] if len(path) >= 2 else None
    raw_edges = get_available_edges(compact_graph, current)

    def allowed(node: int, *, allow_previous: bool) -> bool:
        return (
            node != current
            and (allow_previous or node != previous_node)
            and (current, node) not in used_edges
            and visit_counts.get(node, 0) < max_visits_per_node
        )

    strict_edges = [
        edge for edge in raw_edges
        if allowed(int(edge["node"]), allow_previous=False)
    ]
    recovery_edges = [
        edge for edge in raw_edges
        if allowed(int(edge["node"]), allow_previous=True)
    ]
    backtrack_allowed = not strict_edges and bool(recovery_edges)
    available_edges = recovery_edges if backtrack_allowed else strict_edges

    if candidate_scope == "neighbors":
        candidate_nodes = [int(edge["node"]) for edge in available_edges]
    else:
        strict_nodes = [
            node for node in nodes if allowed(node, allow_previous=False)
        ]
        recovery_nodes = [
            node for node in nodes if allowed(node, allow_previous=True)
        ]
        backtrack_allowed = not strict_nodes and bool(recovery_nodes)
        candidate_nodes = recovery_nodes if backtrack_allowed else strict_nodes

    return {
        "previous_node": previous_node,
        "available_edges": available_edges,
        "candidate_nodes": candidate_nodes,
        "backtrack_allowed": backtrack_allowed,
        "prevented_candidate_count": len(raw_edges) - len(available_edges),
    }

# 모델이 다음 노드를 선택할 때 사용할 입력 데이터 구성
def next_node_state(
    compact_graph: dict[str, Any],
    current: int,
    target: int,
    path: list[int],
    used_edges: set[tuple[int, int]],
    visit_counts: dict[int, int],
    accumulated_distance: float,
    options: dict[str, Any],
    *,
    context_mode: str = "neighbor_context",
    max_visits_per_node: int = MAX_VISITS_PER_NODE,
) -> dict[str, Any]:
    """
    전체 그래프·현재/목표 노드·방문/사용 간선·누적 거리를 담고,
    neighbor_context일 때만 현재 노드의 available_edges를 추가한다.
    """
    if context_mode not in {"neighbor_context", "full_graph_only"}:
        raise ValueError(f"Unsupported context_mode: {context_mode}")
    
    state = {
        "route_graph": compact_graph,
        "current_node": current,
        "previous_node": options["previous_node"],
        "target_node": target,
        "visited_nodes": path,
        "visit_counts": dict(sorted(visit_counts.items())),
        "max_visits_per_node": max_visits_per_node,
        "used_edges": [
            {"from": start, "to": end} for start, end in sorted(used_edges)
        ],
        "backtrack_allowed": options["backtrack_allowed"],
        "accumulated_distance": accumulated_distance,
    }

    if context_mode == "neighbor_context":
        state["available_edges"] = options["available_edges"]
    return state
