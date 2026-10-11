"""Shared iterative route execution for the V2 matrix and final selector benchmark."""
from __future__ import annotations

import math
import time
from typing import Any

from simulation.services.iterative_route_policy import (
    MAX_VISITS_PER_NODE, NEXT_NODE_INSTRUCTIONS, next_node_options, next_node_state,
)
from simulation.services.route_service import validate_and_calculate_path_distance

# 두 시험은 후보 구성·재방문·강제 이동·검증을 이 실행기로 공유한다.
# A* 기준 경로는 실행 후 평가에만 사용하고 모델의 다음 노드를 대신 고르지 않는다.
def _random_path_baseline(
    prepared: dict[str, Any], case: dict[str, Any], candidate_scope: str
) -> float:
    """Probability of reproducing the ground-truth path by uniform choices."""
    probability = 1.0
    visited = [case["expected_path"][0]]
    for current, expected_next in zip(
        case["expected_path"], case["expected_path"][1:]
    ):
        previous_node = visited[-2] if len(visited) >= 2 else None
        if candidate_scope == "neighbors":
            pool = {
                end
                for (edge_start, end) in prepared["edge_weights"]
                if edge_start == current and end != previous_node
            }
        else:
            pool = {
                node
                for node in prepared["nodes"]
                if node != current and node != previous_node
            }
        if expected_next not in pool or not pool:
            return 0.0
        probability *= 1.0 / len(pool)
        visited.append(expected_next)
    return probability


def run_selected_route(
    selector: Any,
    prepared: dict[str, Any],
    case: dict[str, Any],
    candidate_scope: str,
    deadline: float,
    context_mode: str = "neighbor_context",
    max_steps: int | None = None,
    *, instructions: str = NEXT_NODE_INSTRUCTIONS,
) -> dict[str, Any]:
    start, target = case["start"], case["target"]
    current = start
    path = [start]
    steps: list[dict[str, Any]] = []
    used_edges: set[tuple[int, int]] = set()
    visit_counts: dict[int, int] = {start: 1}
    max_visits_per_node = MAX_VISITS_PER_NODE
    api_call_count = 0
    accumulated_distance = 0.0
    error: str | None = None
    failed_step: int | None = None
    invalid_edge_count = 0
    revisit_count = 0
    backtrack_step_count = 0
    cycle_prevented_count = 0
    started = time.perf_counter()
    step_limit = max_steps if max_steps is not None else len(prepared["nodes"]) * 2
    if step_limit < 1:
        raise ValueError("max_steps must be positive")

    for step_index in range(step_limit):
        if current == target:
            break
        # Node 재방문은 복구를 위해 허용하지만 같은 방향성 Edge는 한 번만 사용한다. 
        # 우선 직전 Node를 제외하고, 후보가 없을 때만 미사용 역방향 Edge를 통한 한 단계 backtrack을 허용한다. 
        # Node별 방문은 최대 2회다.
        options = next_node_options(
            prepared["compact_graph"], prepared["nodes"], current, path,
            used_edges, visit_counts, candidate_scope=candidate_scope,
            max_visits_per_node=max_visits_per_node,
        )
        previous_node = options["previous_node"]
        neighbor_edges = options["available_edges"]
        backtrack_allowed = options["backtrack_allowed"]
        candidate_nodes = options["candidate_nodes"]
        prevented_this_step = options["prevented_candidate_count"]
        cycle_prevented_count += prevented_this_step
        if not candidate_nodes:
            error = (
                "순환 방지 조건을 만족하는 이동 후보가 없습니다: "
                f"current={current}"
            )
            failed_step = step_index + 1
            break
        candidates = {
            f"node_{node}": f"Node {node}" for node in candidate_nodes
        }
        available_edges = (
            neighbor_edges if context_mode == "neighbor_context" else None
        )

        # 선택지가 하나면 모델이 판단할 내용이 없다. 
        # 세 selector 모두 choice 후보를 두 개 이상 요구하므로 API를 호출하지 않고 유일한 edge를 강제 이동으로 남긴다.
        if len(candidate_nodes) == 1:
            next_node = candidate_nodes[0]
            weight = prepared["edge_weights"][(current, next_node)]
            revisited = next_node in path
            is_backtrack = next_node == previous_node
            if revisited:
                revisit_count += 1
            if is_backtrack:
                backtrack_step_count += 1
            steps.append(
                {
                    "step": step_index + 1,
                    "current_node": current,
                    "previous_node": previous_node,
                    "candidate_scope": candidate_scope,
                    "context_mode": context_mode,
                    "available_edges": available_edges,
                    "backtrack_allowed": backtrack_allowed,
                    "prevented_candidate_count": prevented_this_step,
                    "used_edges": [list(edge) for edge in sorted(used_edges)],
                    "visit_counts": dict(sorted(visit_counts.items())),
                    "max_visits_per_node": max_visits_per_node,
                    "candidates": candidates,
                    "candidate_count": 1,
                    "choice": f"node_{next_node}",
                    "next_node": next_node,
                    "edge_weight": weight,
                    "forced_step": True,
                    "model_called": False,
                    "accepted": True,
                    "revisited": revisited,
                    "backtrack": is_backtrack,
                    "error": None,
                    "confidence": None,
                    "answer_confidence": None,
                    "probabilities": None,
                    "usage": None,
                    "state_truncated": None,
                    "wall_seconds": 0.0,
                    "model_total_seconds": None,
                    "eval_seconds": None,
                    "runtime": None,
                    "realtime_met": None,
                }
            )
            accumulated_distance += weight
            used_edges.add((current, next_node))
            visit_counts[next_node] = visit_counts.get(next_node, 0) + 1
            path.append(next_node)
            current = next_node
            continue

        state = next_node_state(
            prepared["compact_graph"], current, target, path,
            used_edges, visit_counts, accumulated_distance, options,
            context_mode=context_mode,
            max_visits_per_node=max_visits_per_node,
        )
        step_started = time.perf_counter()
        step_record: dict[str, Any] = {
            "step": step_index + 1,
            "current_node": current,
            "previous_node": previous_node,
            "candidate_scope": candidate_scope,
            "context_mode": context_mode,
            "available_edges": available_edges,
            "backtrack_allowed": backtrack_allowed,
            "prevented_candidate_count": prevented_this_step,
            "used_edges": [list(edge) for edge in sorted(used_edges)],
            "visit_counts": dict(sorted(visit_counts.items())),
            "max_visits_per_node": max_visits_per_node,
            "candidates": candidates,
            "candidate_count": len(candidates),
            "forced_step": False,
            "model_called": True,
        }
        try:
            api_call_count += 1
            result = selector.select_choice(
                state,
                candidates,
                instructions,
                question_id=f"route_{start}_{target}_step_{step_index + 1}",
            )
            step_wall = time.perf_counter() - step_started
            choice = str(result.get("choice", ""))
            step_record.update(
                choice=choice,
                confidence=result.get("confidence"),
                answer_confidence=result.get("answer_confidence"),
                probabilities=result.get("probabilities"),
                usage=result.get("usage"),
                state_truncated=result.get("state_truncated"),
                wall_seconds=step_wall,
                model_total_seconds=result.get("total_duration_seconds"),
                eval_seconds=result.get("eval_duration_seconds"),
                runtime=result.get("runtime"),
                realtime_met=step_wall <= deadline,
            )
            if not choice.startswith("node_"):
                raise ValueError(f"잘못된 next-node 응답: {choice!r}")
            next_node = int(choice.removeprefix("node_"))
            step_record["next_node"] = next_node
            revisited = next_node in path
            if revisited:
                revisit_count += 1
            step_record["revisited"] = revisited
            edge_key = (current, next_node)
            if edge_key in used_edges:
                raise ValueError(
                    f"이미 사용한 방향성 edge 재선택: {current} -> {next_node}"
                )
            if visit_counts.get(next_node, 0) >= max_visits_per_node:
                raise ValueError(f"Node 방문 횟수 초과: node={next_node}")
            if edge_key not in prepared["edge_weights"]:
                invalid_edge_count += 1
                raise ValueError(f"존재하지 않는 방향성 edge: {current} -> {next_node}")
            weight = prepared["edge_weights"][edge_key]
            is_backtrack = next_node == previous_node
            if is_backtrack:
                backtrack_step_count += 1
            step_record.update(
                edge_weight=weight,
                backtrack=is_backtrack,
                accepted=True,
                error=None,
            )
            steps.append(step_record)
            accumulated_distance += weight
            used_edges.add(edge_key)
            visit_counts[next_node] = visit_counts.get(next_node, 0) + 1
            path.append(next_node)
            current = next_node
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"
            failed_step = step_index + 1
            step_record.update(
                accepted=False,
                error=error,
                wall_seconds=step_record.get(
                    "wall_seconds", time.perf_counter() - step_started
                ),
            )
            steps.append(step_record)
            break

    if error is None and current != target:
        error = (
            f"최대 단계 초과: max_steps={step_limit}, "
            f"target={target}, current={current}"
        )

    valid_path = False
    recalculated_distance = None
    if error is None:
        try:
            _, recalculated_distance = validate_and_calculate_path_distance(
                prepared["points"],
                prepared["edges"],
                path,
                start,
                target,
            )
            valid_path = True
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"

    wall_seconds = time.perf_counter() - started
    # 강제 이동은 모델 입력이 없으므로 Laya 입력 잘림 집계에서 제외한다.
    truncation_values = [
        step.get("state_truncated")
        for step in steps
        if step.get("model_called") is True
    ]
    state_truncated_count = sum(value is True for value in truncation_values)
    state_truncation_reported_count = sum(
        isinstance(value, bool) for value in truncation_values
    )
    truncation_reporting_complete = (
        state_truncation_reported_count == len(truncation_values)
        if truncation_values else None
    )
    # Laya만 tokenizer 사용량과 잘림 여부를 보고한다. 미보고(None)를
    # '잘리지 않음'으로 오인하지 않고 별도 상태로 남긴다.
    full_graph_input_preserved = (
        truncation_reporting_complete and state_truncated_count == 0
        if getattr(selector, "name", None) == "laya"
        else None
    )
    return {
        "path": path,
        "steps": steps,
        "api_call_count": api_call_count,
        "max_steps": step_limit,
        "candidate_scope": candidate_scope,
        "context_mode": context_mode,
        "failed_step": failed_step,
        "invalid_edge_count": invalid_edge_count,
        "revisit_count": revisit_count,
        "backtrack_step_count": backtrack_step_count,
        "cycle_prevented_count": cycle_prevented_count,
        "used_edge_count": len(used_edges),
        "max_node_visit_count": max(visit_counts.values()),
        "visit_counts": dict(sorted(visit_counts.items())),
        "valid_path": valid_path,
        "reached_target": valid_path,
        "has_revisit": revisit_count > 0,
        "non_revisiting_valid_path": valid_path and revisit_count == 0,
        "step_excess": max(0, len(path) - len(case["expected_path"])) if case.get("expected_path") else None,
        "recalculated_distance": recalculated_distance,
        "exact_path_match": path == case.get("expected_path"),
        "distance_match": (
            recalculated_distance is not None
            and case.get("expected_distance") is not None
            and math.isclose(
                recalculated_distance,
                case["expected_distance"],
                rel_tol=1e-9,
                abs_tol=1e-9,
            )
        ),
        "distance_ratio": (
            recalculated_distance / case["expected_distance"]
            if recalculated_distance is not None and case.get("expected_distance") else None
        ),
        "random_baseline_path_probability": _random_path_baseline(
            prepared, case, candidate_scope
        ) if case.get("expected_path") else None,
        "wall_seconds": wall_seconds,
        "state_truncated_count": state_truncated_count,
        "state_truncation_reported_count": state_truncation_reported_count,
        "state_truncation_reporting_complete": truncation_reporting_complete,
        "full_graph_input_preserved": full_graph_input_preserved,
        "model_total_seconds": sum(
            float(step["model_total_seconds"])
            for step in steps
            if step.get("model_total_seconds") is not None
        ),
        "step_wall_seconds": [step["wall_seconds"] for step in steps],
        "error": error,
    }


