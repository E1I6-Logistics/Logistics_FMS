"""Compare Ollama, Laya, and Kev through iterative next-node selection."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import random
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean, median
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from simulation.evaluation.device_metadata import git_metadata, selector_device_metadata
from simulation.evaluation.graph_path import resolve_graph_path
from simulation.route_selector import get_selector
from simulation.services.route_service import (
    build_compact_adjacency_graph,
    build_route_inputs,
    build_edge_weight_lookup,
    get_available_edges,
    plan_route,
    validate_and_calculate_path_distance,
)

CONFIG_PATH = ROOT / "simulation" / "evaluation" / "route_generation_benchmark.json"
MATRIX_MANIFEST_FILENAME = "selector_iterative_matrix_manifest.json"
TRIALS_FILENAME = "selector_iterative_route_trials.jsonl"
SUMMARY_FILENAME = "selector_iterative_route_summary.json"
CSV_FILENAME = "selector_iterative_route_samples.csv"
MANIFEST_FILENAME = "manifest.json"
DEFAULT_CASE_COUNT = 5
DEFAULT_RESULTS_DIR = ROOT / "simulation" / "benchmark_results"
DOCKING_NODE_IDS = tuple(range(7))

NEXT_NODE_INSTRUCTIONS = (
    "Select exactly one next node for the minimum-total-weight route from "
    "current_node to target_node. The selected node must be connected by one "
    "directed edge from current_node. Use the CompactAdjacencyGraph weight exactly "
    "as stored. Choose only from the supplied criteria. If available_edges "
    "is present, it is an exact lookup of outgoing edges and stored weights; "
    "choose only a node "
    "listed there. Never reuse a directed edge listed in used_edges. Select "
    "only a node whose visit count is below max_visits_per_node. Do not return "
    "to previous_node unless backtrack_allowed is true. Older nodes may be "
    "revisited within the visit limit when needed to reach the target. Return "
    "only the selected criteria ID."
)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _json_dump(path: Path, value: dict[str, Any]) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _append_jsonl(path: Path, value: dict[str, Any]) -> None:
    with path.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(value, ensure_ascii=False) + "\n")


def _percentile(values: list[float], percentile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered) - 1) * percentile
    lower, upper = math.floor(position), math.ceil(position)
    if lower == upper:
        return ordered[lower]
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def _stats(values: list[float]) -> dict[str, float | int | None]:
    return {
        "count": len(values),
        "mean_seconds": mean(values) if values else None,
        "median_seconds": median(values) if values else None,
        "p95_seconds": _percentile(values, 0.95),
        "min_seconds": min(values) if values else None,
        "max_seconds": max(values) if values else None,
    }


def _generate_random_cases(
    graph: dict[str, Any],
    nodes: list[int],
    *,
    case_count: int,
    seed: int,
) -> list[dict[str, Any]]:
    """Create reproducible unique Start→Docking pairs with disjoint node sets."""
    docking_nodes = [node for node in DOCKING_NODE_IDS if node in nodes]
    if case_count < 1:
        raise ValueError("case_count must be positive")
    if case_count > len(docking_nodes):
        raise ValueError(
            f"case_count={case_count} exceeds docking nodes={len(docking_nodes)}"
        )
    if len(nodes) - case_count < case_count:
        raise ValueError(
            "시작 Node 집합과 도착 Node 집합을 겹치지 않게 만들 수 없습니다."
        )

    rng = random.Random(seed)
    # A retry loop also protects future directed maps where some random pairs
    # may not have a valid route. The recorded seed reproduces the same retries.
    for _attempt in range(1_000):
        targets = rng.sample(docking_nodes, case_count)
        start_pool = [node for node in nodes if node not in targets]
        starts = rng.sample(start_pool, case_count)
        cases: list[dict[str, Any]] = []
        try:
            for start, target in zip(starts, targets):
                baseline = plan_route(
                    str(start), str(target), graph, require_stored_weight=True
                )
                cases.append(
                    {
                        "start": start,
                        "target": target,
                        "expected_path": [
                            int(node) for node in baseline["node_ids"]
                        ],
                        "expected_distance": float(baseline["cost"]),
                    }
                )
        except ValueError:
            continue
        return cases
    raise RuntimeError("유효한 랜덤 Start→Docking 경로 조합을 만들지 못했습니다.")


def _generate_all_pairs(
    graph: dict[str, Any], nodes: list[int]
) -> list[dict[str, Any]]:
    """Create every reachable Start→Docking pair (12×7−7 = 77 here)."""
    cases: list[dict[str, Any]] = []
    for start in nodes:
        for target in DOCKING_NODE_IDS:
            if target not in nodes or start == target:
                continue
            baseline = plan_route(
                str(start), str(target), graph, require_stored_weight=True
            )
            cases.append(
                {
                    "start": start,
                    "target": target,
                    "expected_path": [int(node) for node in baseline["node_ids"]],
                    "expected_distance": float(baseline["cost"]),
                }
            )
    return cases


def _prepare(
    *,
    case_count: int = DEFAULT_CASE_COUNT,
    route_seed: int | None = None,
    graph_path: Path | None = None,
    case_mode: str = "random",
) -> dict[str, Any]:
    config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    graph_path = resolve_graph_path(
        graph_path,
        fallback=ROOT / config["graph"]["path"],
    )
    if case_mode not in {"random", "all-pairs"}:
        raise ValueError("case_mode must be 'random' or 'all-pairs'")
    graph = json.loads(graph_path.read_text(encoding="utf-8"))
    points, edges = build_route_inputs(graph, require_stored_weight=True)
    edge_weights = build_edge_weight_lookup(points, edges)
    compact_graph = build_compact_adjacency_graph(
        graph,
        graph_path.name,
        require_stored_weight=True,
    )

    # 시드를 지정하지 않으면 실행마다 새 경로 조합을 만든다. 실제 사용한
    # 시드는 manifest에 기록하므로 다른 모델 비교 시 그대로 재사용할 수 있다.
    effective_seed = (
        int(route_seed)
        if route_seed is not None
        else random.SystemRandom().randrange(1, 2**63)
    )
    nodes = sorted(points)
    cases = (
        _generate_all_pairs(graph, nodes)
        if case_mode == "all-pairs"
        else _generate_random_cases(
            graph,
            nodes,
            case_count=case_count,
            seed=effective_seed,
        )
    )
    return {
        "graph_path": graph_path,
        "graph": graph,
        "compact_graph": compact_graph,
        "points": points,
        "edges": edges,
        "edge_weights": edge_weights,
        "nodes": nodes,
        "cases": cases,
        "route_seed": effective_seed if case_mode == "random" else None,
        "case_mode": case_mode,
        "docking_nodes": [node for node in DOCKING_NODE_IDS if node in nodes],
    }


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


def _run_route(
    selector: Any,
    prepared: dict[str, Any],
    case: dict[str, Any],
    candidate_scope: str,
    deadline: float,
    context_mode: str = "neighbor_context",
    max_steps: int | None = None,
) -> dict[str, Any]:
    start, target = case["start"], case["target"]
    current = start
    path = [start]
    steps: list[dict[str, Any]] = []
    used_edges: set[tuple[int, int]] = set()
    visit_counts: dict[int, int] = {start: 1}
    max_visits_per_node = 2
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
        # Node 재방문은 복구를 위해 허용하지만 같은 방향성 Edge는 한 번만
        # 사용한다. 우선 직전 Node를 제외하고, 후보가 없을 때만 미사용 역방향
        # Edge를 통한 한 단계 backtrack을 허용한다. Node별 방문은 최대 2회다.
        previous_node = path[-2] if len(path) >= 2 else None
        raw_neighbor_edges = get_available_edges(
            prepared["compact_graph"], current
        )

        def edge_allowed(edge: dict[str, Any], *, allow_previous: bool) -> bool:
            node = int(edge["node"])
            return (
                node != current
                and (allow_previous or node != previous_node)
                and (current, node) not in used_edges
                and visit_counts.get(node, 0) < max_visits_per_node
            )

        strict_neighbor_edges = [
            edge for edge in raw_neighbor_edges
            if edge_allowed(edge, allow_previous=False)
        ]
        recovery_neighbor_edges = [
            edge for edge in raw_neighbor_edges
            if edge_allowed(edge, allow_previous=True)
        ]
        backtrack_allowed = not strict_neighbor_edges and bool(recovery_neighbor_edges)
        neighbor_edges = (
            recovery_neighbor_edges if backtrack_allowed else strict_neighbor_edges
        )
        prevented_this_step = len(raw_neighbor_edges) - len(neighbor_edges)
        cycle_prevented_count += prevented_this_step

        if candidate_scope == "neighbors":
            candidate_nodes = [int(edge["node"]) for edge in neighbor_edges]
        else:
            strict_nodes = [
                node for node in prepared["nodes"]
                if node != current
                and node != previous_node
                and (current, node) not in used_edges
                and visit_counts.get(node, 0) < max_visits_per_node
            ]
            recovery_nodes = [
                node for node in prepared["nodes"]
                if node != current
                and (current, node) not in used_edges
                and visit_counts.get(node, 0) < max_visits_per_node
            ]
            backtrack_allowed = not strict_nodes and bool(recovery_nodes)
            candidate_nodes = recovery_nodes if backtrack_allowed else strict_nodes
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

        # 선택지가 하나면 모델이 판단할 내용이 없다. 세 selector 모두 choice 후보를
        # 두 개 이상 요구하므로 API를 호출하지 않고 유일한 edge를 강제 이동으로 남긴다.
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

        state = {
            "route_graph": prepared["compact_graph"],
            "current_node": current,
            "previous_node": previous_node,
            "target_node": target,
            "visited_nodes": path,
            "visit_counts": dict(sorted(visit_counts.items())),
            "max_visits_per_node": max_visits_per_node,
            "used_edges": [
                {"from": edge_start, "to": edge_end}
                for edge_start, edge_end in sorted(used_edges)
            ],
            "backtrack_allowed": backtrack_allowed,
            "accumulated_distance": accumulated_distance,
        }
        if available_edges is not None:
            state["available_edges"] = available_edges
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
                NEXT_NODE_INSTRUCTIONS,
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
        "step_excess": max(0, len(path) - len(case["expected_path"])),
        "recalculated_distance": recalculated_distance,
        "exact_path_match": path == case["expected_path"],
        "distance_match": (
            recalculated_distance is not None
            and math.isclose(
                recalculated_distance,
                case["expected_distance"],
                rel_tol=1e-9,
                abs_tol=1e-9,
            )
        ),
        "distance_ratio": (
            recalculated_distance / case["expected_distance"]
            if recalculated_distance is not None else None
        ),
        "random_baseline_path_probability": _random_path_baseline(
            prepared, case, candidate_scope
        ),
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


def _summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    completed = [row for row in rows if row["error"] is None]
    all_steps = [step for row in rows for step in row["steps"]]
    model_steps = [step for step in all_steps if step.get("model_called") is True]
    # 입력 토큰 수와 state 잘림 여부는 현재 Laya selector만 보고한다.
    # Kev/Ollama의 None 값을 잘림 미보고 오류로 집계하지 않는다.
    laya_rows = [row for row in rows if row.get("selector_name") == "laya"]
    return {
        "trial_count": len(rows),
        "completed_count": len(completed),
        "error_count": len(rows) - len(completed),
        "valid_path_count": sum(bool(row["valid_path"]) for row in rows),
        "reached_target_count": sum(bool(row["reached_target"]) for row in rows),
        "non_revisiting_valid_path_count": sum(
            bool(row["non_revisiting_valid_path"]) for row in rows
        ),
        "revisit_trial_count": sum(bool(row["has_revisit"]) for row in rows),
        "mean_step_excess": mean(row["step_excess"] for row in rows) if rows else None,
        "exact_path_match_count": sum(bool(row["exact_path_match"]) for row in rows),
        "distance_match_count": sum(bool(row["distance_match"]) for row in rows),
        "invalid_edge_count": sum(row["invalid_edge_count"] for row in rows),
        "revisit_count": sum(row["revisit_count"] for row in rows),
        "backtrack_step_count": sum(row["backtrack_step_count"] for row in rows),
        "cycle_prevented_count": sum(row["cycle_prevented_count"] for row in rows),
        "max_node_visit_count": max(
            (row["max_node_visit_count"] for row in rows), default=0
        ),
        "forced_step_count": sum(
            step.get("forced_step") is True for step in all_steps
        ),
        "model_decision_step_count": len(model_steps),
        "state_truncated_trial_count": sum(
            row["state_truncated_count"] > 0 for row in laya_rows
        ),
        "state_truncation_unreported_trial_count": sum(
            row["state_truncation_reporting_complete"] is False for row in laya_rows
        ),
        "full_graph_input_preserved_count": sum(
            row["full_graph_input_preserved"] is True for row in laya_rows
        ),
        "exact_path_accuracy": (
            sum(bool(row["exact_path_match"]) for row in rows) / len(rows)
            if rows else None
        ),
        "mean_api_call_count": (
            mean(row["api_call_count"] for row in rows) if rows else None
        ),
        "mean_distance_ratio": (
            mean(
                row["distance_ratio"]
                for row in rows
                if row["distance_ratio"] is not None
            )
            if any(row["distance_ratio"] is not None for row in rows)
            else None
        ),
        "mean_random_baseline_path_probability": (
            mean(row["random_baseline_path_probability"] for row in rows)
            if rows else None
        ),
        "step_realtime_met_count": sum(
            step.get("realtime_met") is True for step in model_steps
        ),
        "step_realtime_met_rate": (
            sum(step.get("realtime_met") is True for step in model_steps)
            / len(model_steps)
            if model_steps else None
        ),
        "mean_answer_confidence": (
            mean(
                float(step["answer_confidence"])
                for step in model_steps
                if step.get("answer_confidence") is not None
            )
            if any(step.get("answer_confidence") is not None for step in model_steps)
            else None
        ),
        "wall_latency": _stats([row["wall_seconds"] for row in completed]),
        "all_trial_wall_latency": _stats([row["wall_seconds"] for row in rows]),
        "step_wall_latency": _stats(
            [step["wall_seconds"] for step in model_steps if "wall_seconds" in step]
        ),
        "model_total_latency": _stats(
            [row["model_total_seconds"] for row in completed]
        ),
    }


def _safe_name(value: Any) -> str:
    return re.sub(r"[^a-zA-Z0-9._-]+", "-", str(value or "unknown")).strip("-")


def default_output_path(selector: Any) -> Path:
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    return DEFAULT_RESULTS_DIR / (
        f"{_safe_name(getattr(selector, 'name', selector.__class__.__name__))}-"
        f"{_safe_name(getattr(selector, 'model', None))}-iterative-{timestamp}"
    )


def default_matrix_output_path() -> Path:
    """Return one parent directory for a configured multi-model run."""
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    return DEFAULT_RESULTS_DIR / f"ollama-iterative-matrix-{timestamp}"


def _resolve_model_specs(
    config: dict[str, Any], selected_models: list[str] | None = None
) -> list[dict[str, Any]]:
    """Merge common Ollama defaults with each enabled model entry."""
    defaults = config.get("ollama_defaults", {})
    if not isinstance(defaults, dict):
        raise ValueError("ollama_defaults must be an object")
    default_options = defaults.get("options", {})
    if not isinstance(default_options, dict):
        raise ValueError("ollama_defaults.options must be an object")

    raw_models = config.get("models")
    if not isinstance(raw_models, list) or not raw_models:
        raise ValueError("models must be a non-empty array")
    requested = set(selected_models or [])
    seen: set[str] = set()
    resolved: list[dict[str, Any]] = []
    for raw in raw_models:
        if not isinstance(raw, dict) or not str(raw.get("name", "")).strip():
            raise ValueError("each model entry must contain a non-empty name")
        name = str(raw["name"]).strip()
        if name in seen:
            raise ValueError(f"duplicate model name: {name}")
        seen.add(name)
        if raw.get("enabled", True) is not True:
            continue
        if requested and name not in requested:
            continue
        raw_options = raw.get("options", {})
        if not isinstance(raw_options, dict):
            raise ValueError(f"model options must be an object: {name}")
        spec = {
            key: value
            for key, value in defaults.items()
            if key != "options"
        }
        spec.update(
            {
                key: value
                for key, value in raw.items()
                if key not in {"enabled", "options"}
            }
        )
        spec["name"] = name
        spec["options"] = {**default_options, **raw_options}
        resolved.append(spec)

    unknown = requested - seen
    if unknown:
        raise ValueError(
            "models not present in config: " + ", ".join(sorted(unknown))
        )
    disabled = requested - {spec["name"] for spec in resolved}
    if disabled:
        raise ValueError(
            "requested models are disabled: " + ", ".join(sorted(disabled))
        )
    if not resolved:
        raise ValueError("no enabled models selected")
    return resolved


def load_iterative_config(
    config_path: Path,
    selected_models: list[str] | None = None,
) -> dict[str, Any]:
    """Validate the JSON config without contacting Ollama."""
    config_path = config_path.resolve()
    config = json.loads(config_path.read_text(encoding="utf-8"))
    if not isinstance(config, dict):
        raise ValueError("benchmark config must be a JSON object")
    graph = config.get("graph")
    if not isinstance(graph, dict) or not graph.get("path"):
        raise ValueError("graph.path is required")
    graph_path = Path(str(graph["path"]))
    if not graph_path.is_absolute():
        graph_path = ROOT / graph_path
    graph_path = graph_path.resolve()
    if not graph_path.is_file():
        raise FileNotFoundError(f"graph file not found: {graph_path}")
    actual_sha256 = hashlib.sha256(graph_path.read_bytes()).hexdigest()
    expected_sha256 = graph.get("sha256")
    if expected_sha256 and str(expected_sha256) != actual_sha256:
        raise ValueError(
            f"graph SHA-256 mismatch: expected={expected_sha256}, "
            f"actual={actual_sha256}"
        )

    settings = config.get("settings")
    if not isinstance(settings, dict):
        raise ValueError("settings must be an object")
    required = {
        "case_mode", "case_count", "repeats", "warmups", "route_seed",
        "candidate_scope", "context_mode", "max_steps", "deadline_seconds",
    }
    missing = sorted(required - settings.keys())
    if missing:
        raise ValueError("missing settings: " + ", ".join(missing))
    if settings["case_mode"] not in {"random", "all-pairs"}:
        raise ValueError("settings.case_mode must be random or all-pairs")
    if settings["candidate_scope"] not in {"neighbors", "all"}:
        raise ValueError("settings.candidate_scope must be neighbors or all")
    if settings["context_mode"] not in {"full_graph_only", "neighbor_context"}:
        raise ValueError(
            "settings.context_mode must be full_graph_only or neighbor_context"
        )

    models = _resolve_model_specs(config, selected_models)
    return {
        "config_path": config_path,
        "config_sha256": hashlib.sha256(config_path.read_bytes()).hexdigest(),
        "graph_path": graph_path,
        "graph_sha256": actual_sha256,
        "settings": settings,
        "models": models,
    }


def _build_configured_ollama_selector(spec: dict[str, Any]) -> Any:
    """Create one Ollama selector from a resolved model configuration."""
    from simulation.llm_providers.ollama_provider import OllamaPathProvider
    from simulation.route_selector.ollama_selector import OllamaSelector

    provider = OllamaPathProvider(
        model=spec["name"],
        host=spec.get("host"),
        timeout_seconds=float(spec.get("timeout_seconds", 60)),
        options=dict(spec["options"]),
        keep_alive=str(spec.get("keep_alive", "5m")),
        think=spec.get("think"),
    )
    return OllamaSelector(provider)


def _selector_model_configuration(selector: Any) -> dict[str, Any] | None:
    """Expose the resolved Ollama request options in each result manifest."""
    provider = getattr(selector, "provider", None)
    if provider is None or getattr(selector, "name", None) != "ollama":
        return None
    return {
        "host": getattr(provider, "host", None),
        "timeout_seconds": getattr(provider, "timeout_seconds", None),
        "keep_alive": getattr(provider, "keep_alive", None),
        "think": getattr(provider, "think", None),
        "options": getattr(provider, "options", None),
    }


def _preflight_selector(selector: Any) -> None:
    """Fail before trials when a selector runtime or configured model is unavailable."""
    ensure_runtime = getattr(selector, "_ensure_runtime", None)
    if callable(ensure_runtime):
        ensure_runtime()
        return
    ensure_agent = getattr(selector, "_ensure_agent", None)
    if callable(ensure_agent):
        ensure_agent()
        return
    provider = getattr(selector, "provider", None)
    client = getattr(provider, "client", None)
    if client is not None and hasattr(client, "list"):
        response = client.list()
        payload = (
            response.model_dump(mode="json")
            if hasattr(response, "model_dump")
            else dict(response)
        )
        names = {
            str(item.get("name") or item.get("model"))
            for item in payload.get("models", [])
        }
        if getattr(selector, "model", None) not in names:
            raise RuntimeError(
                f"설정한 Ollama 모델이 설치되어 있지 않습니다: {selector.model}"
            )


def run_benchmark(
    output: Path,
    *,
    repeats: int = 5,
    warmups: int = 1,
    case_count: int = DEFAULT_CASE_COUNT,
    route_seed: int | None = None,
    graph_path: Path | None = None,
    case_mode: str = "random",
    candidate_scope: str = "neighbors",
    context_mode: str = "neighbor_context",
    max_steps: int | None = None,
    deadline: float = 0.15,
    selector: Any | None = None,
    progress: bool = True,
) -> dict[str, Any]:
    if repeats < 1 or warmups < 0:
        raise ValueError("repeats must be positive and warmups must be non-negative")
    if case_count < 1:
        raise ValueError("case_count must be positive")
    if candidate_scope not in {"neighbors", "all"}:
        raise ValueError("candidate_scope must be 'neighbors' or 'all'")
    if context_mode not in {"full_graph_only", "neighbor_context"}:
        raise ValueError(
            "context_mode must be 'full_graph_only' or 'neighbor_context'"
        )
    if max_steps is not None and max_steps < 1:
        raise ValueError("max_steps must be positive")
    if deadline <= 0:
        raise ValueError("deadline must be positive")
    output = output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    trials_path = output / TRIALS_FILENAME
    if trials_path.exists() and trials_path.stat().st_size:
        raise FileExistsError(f"existing trial file would be overwritten: {trials_path}")

    prepared = _prepare(
        case_count=case_count,
        route_seed=route_seed,
        graph_path=graph_path,
        case_mode=case_mode,
    )
    effective_max_steps = max_steps or len(prepared["nodes"]) * 2
    selector = selector or get_selector()
    selector_name = getattr(selector, "name", selector.__class__.__name__)
    manifest = {
        "benchmark": "selector-iterative-next-node-v1",
        "status": "running",
        "started_at": _utc_now(),
        "source": git_metadata(ROOT),
        "selector_name": selector_name,
        "requested_model": getattr(selector, "model", None),
        "model_configuration": _selector_model_configuration(selector),
        "graph": {
            "source": str(prepared["graph_path"].relative_to(ROOT)),
            "sha256": hashlib.sha256(prepared["graph_path"].read_bytes()).hexdigest(),
            "model_input_format": "CompactAdjacencyGraph",
            "node_count": len(prepared["nodes"]),
        },
        "settings": {
            "repeats_per_case": repeats,
            "warmups": warmups,
            "case_count": len(prepared["cases"]),
            "route_seed": prepared["route_seed"],
            "case_mode": prepared["case_mode"],
            "case_generation_policy": (
                "all_reachable_start_to_docking_pairs"
                if prepared["case_mode"] == "all-pairs"
                else "seeded_unique_disjoint_start_to_docking"
            ),
            "instructions": NEXT_NODE_INSTRUCTIONS,
            "instructions_sha256": hashlib.sha256(
                NEXT_NODE_INSTRUCTIONS.encode("utf-8")
            ).hexdigest(),
            "prompt_version": "iterative-next-node-v2",
            "docking_target_nodes": prepared["docking_nodes"],
            "generated_cases": [
                {"start": case["start"], "target": case["target"]}
                for case in prepared["cases"]
            ],
            "expected_trial_count": len(prepared["cases"]) * repeats,
            "questions_per_api_request": 1,
            "candidate_scope": candidate_scope,
            "context_mode": context_mode,
            "context_policy": (
                "exact_current_node_adjacency_each_step"
                if context_mode == "neighbor_context"
                else "none"
            ),
            "max_steps": effective_max_steps,
            "revisit_policy": "node_revisit_allowed_without_directed_edge_reuse",
            "max_visits_per_node": 2,
            "backtrack_policy": "previous_node_allowed_only_when_no_strict_candidate",
            "realtime_deadline_seconds": deadline,
            "python_role": "state storage, validation, and deterministic single-candidate transition",
            "single_candidate_policy": "forced_step_without_model_call",
            "selector_max_length": getattr(selector, "max_length", None),
            "selector_head_max_length": getattr(selector, "head_max_length", None),
        },
        "device": selector_device_metadata(selector),
    }
    _json_dump(output / MANIFEST_FILENAME, manifest)

    try:
        _preflight_selector(selector)
    except Exception as exc:
        manifest.update(
            status="failed",
            completed_at=_utc_now(),
            failure_stage="selector_preflight",
            failure=f"{type(exc).__name__}: {exc}",
        )
        _json_dump(output / MANIFEST_FILENAME, manifest)
        release = getattr(selector, "release", None)
        if callable(release):
            release()
        raise

    for warmup in range(1, warmups + 1):
        _run_route(
            selector, prepared, prepared["cases"][0], candidate_scope, deadline,
            context_mode, effective_max_steps
        )
        if progress:
            print(f"warmup {warmup}/{warmups} complete")

    rows: list[dict[str, Any]] = []
    last_result = None
    for case in prepared["cases"]:
        for repeat in range(1, repeats + 1):
            result = _run_route(
                selector, prepared, case, candidate_scope, deadline, context_mode,
                effective_max_steps
            )
            last_result = result
            row = {
                "timestamp": _utc_now(),
                "selector_name": selector_name,
                "requested_model": getattr(selector, "model", None),
                "start_node": case["start"],
                "target_node": case["target"],
                "repeat": repeat,
                "expected_path": case["expected_path"],
                "expected_distance": case["expected_distance"],
                **result,
            }
            rows.append(row)
            _append_jsonl(trials_path, row)
            if progress:
                print(
                    f"{case['start']}->{case['target']} {repeat}/{repeats} "
                    f"path={result['path']} exact={result['exact_path_match']} "
                    f"calls={result['api_call_count']} error={result['error']}"
                )

    groups = []
    for case in prepared["cases"]:
        selected = [
            row for row in rows
            if row["start_node"] == case["start"]
            and row["target_node"] == case["target"]
        ]
        groups.append(
            {
                "start_node": case["start"],
                "target_node": case["target"],
                **_summarize(selected),
            }
        )
    summary = {
        "benchmark": manifest["benchmark"],
        "created_at": _utc_now(),
        "selector_name": selector_name,
        "requested_model": getattr(selector, "model", None),
        "device": selector_device_metadata(selector, last_result),
        "settings": manifest["settings"],
        "overall": _summarize(rows),
        "routes": groups,
    }
    _json_dump(output / SUMMARY_FILENAME, summary)

    fields = [
        "timestamp", "selector_name", "requested_model", "start_node",
        "target_node", "repeat", "expected_path", "path", "expected_distance",
        "recalculated_distance", "distance_ratio", "api_call_count", "valid_path",
        "reached_target", "has_revisit", "non_revisiting_valid_path", "step_excess",
        "random_baseline_path_probability",
        "candidate_scope", "context_mode", "failed_step",
        "invalid_edge_count", "revisit_count", "backtrack_step_count",
        "cycle_prevented_count", "used_edge_count", "max_node_visit_count",
        "visit_counts",
        "exact_path_match", "distance_match", "wall_seconds",
        "model_total_seconds", "state_truncated_count",
        "state_truncation_reported_count",
        "state_truncation_reporting_complete", "full_graph_input_preserved",
        "steps", "error",
    ]
    with (output / CSV_FILENAME).open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            exported = {field: row.get(field) for field in fields}
            for field in ("expected_path", "path", "steps", "visit_counts"):
                exported[field] = json.dumps(
                    row.get(field), ensure_ascii=False, separators=(",", ":")
                )
            writer.writerow(exported)

    manifest.update(
        status="complete",
        completed_at=_utc_now(),
        completed_trial_count=len(rows),
        device=summary["device"],
        output_files=[
            MANIFEST_FILENAME, TRIALS_FILENAME, SUMMARY_FILENAME, CSV_FILENAME
        ],
    )
    _json_dump(output / MANIFEST_FILENAME, manifest)
    release = getattr(selector, "release", None)
    if callable(release):
        release()
    return summary


def run_configured_benchmarks(
    config_path: Path,
    output: Path,
    *,
    selected_models: list[str] | None = None,
    progress: bool = True,
) -> dict[str, Any]:
    """Run the same iterative cases for selected Ollama models."""
    resolved = load_iterative_config(config_path, selected_models)
    settings = resolved["settings"]
    output = output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    matrix_path = output / MATRIX_MANIFEST_FILENAME
    if matrix_path.exists():
        raise FileExistsError(
            f"existing matrix manifest would be overwritten: {matrix_path}"
        )
    manifest: dict[str, Any] = {
        "benchmark": "selector-iterative-ollama-matrix-v1",
        "status": "running",
        "started_at": _utc_now(),
        "source": git_metadata(ROOT),
        "config": {
            "path": str(resolved["config_path"]),
            "sha256": resolved["config_sha256"],
        },
        "graph": {
            "path": str(resolved["graph_path"].relative_to(ROOT)),
            "sha256": resolved["graph_sha256"],
        },
        "settings": settings,
        "models": resolved["models"],
        "results": [],
    }
    _json_dump(matrix_path, manifest)
    try:
        for spec in resolved["models"]:
            model_name = spec["name"]
            if progress:
                print(f"=== Ollama model: {model_name} ===")
            selector = _build_configured_ollama_selector(spec)
            model_output = output / _safe_name(model_name)
            summary = run_benchmark(
                model_output,
                repeats=int(settings["repeats"]),
                warmups=int(settings["warmups"]),
                case_count=int(settings["case_count"]),
                route_seed=(
                    int(settings["route_seed"])
                    if settings["route_seed"] is not None else None
                ),
                graph_path=resolved["graph_path"],
                case_mode=str(settings["case_mode"]),
                candidate_scope=str(settings["candidate_scope"]),
                context_mode=str(settings["context_mode"]),
                max_steps=(
                    int(settings["max_steps"])
                    if settings["max_steps"] is not None else None
                ),
                deadline=float(settings["deadline_seconds"]),
                selector=selector,
                progress=progress,
            )
            manifest["results"].append(
                {
                    "model": model_name,
                    "output": str(model_output.relative_to(output)),
                    "status": "complete",
                    "overall": summary["overall"],
                }
            )
            _json_dump(matrix_path, manifest)
    except Exception as exc:
        manifest.update(
            status="failed",
            completed_at=_utc_now(),
            failure_model=locals().get("model_name"),
            failure=f"{type(exc).__name__}: {exc}",
        )
        _json_dump(matrix_path, manifest)
        raise
    manifest.update(status="complete", completed_at=_utc_now())
    _json_dump(matrix_path, manifest)
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--config",
        type=Path,
        default=None,
        help=(
            "Ollama 다중 모델 JSON 설정. 이 모드에서는 graph/case/repeat 옵션을 "
            "JSON에서 읽습니다."
        ),
    )
    parser.add_argument(
        "--model",
        action="append",
        default=[],
        help="JSON models 중 실행할 모델. 여러 번 지정 가능 (미지정 시 enabled 전체)",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="JSON·Graph hash·모델 설정만 검증하고 Ollama에는 요청하지 않음",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="결과 폴더 (미지정 시 selector와 model 이름으로 자동 생성)",
    )
    parser.add_argument(
        "--graph",
        type=Path,
        default=None,
        help="사용할 GeoJSON 경로 (기본: LLM_ROUTE_GRAPH, 없으면 benchmark JSON 설정)",
    )
    parser.add_argument(
        "--case-mode", choices=("random", "all-pairs"), default="random"
    )
    parser.add_argument("--repeats", type=int, default=5)
    parser.add_argument("--warmups", type=int, default=1)
    parser.add_argument("--case-count", type=int, default=DEFAULT_CASE_COUNT)
    parser.add_argument(
        "--route-seed",
        type=int,
        default=None,
        help="랜덤 경로 생성 시드 (미지정 시 실행마다 새 시드 생성)",
    )
    parser.add_argument(
        "--candidate-scope", choices=("neighbors", "all"), default="neighbors"
    )
    parser.add_argument(
        "--context-mode",
        choices=("full_graph_only", "neighbor_context"),
        default="neighbor_context",
    )
    parser.add_argument(
        "--max-steps",
        type=int,
        default=None,
        help="목적지 미도착 시 중단할 최대 이동 횟수 (기본: Node 수의 2배)",
    )
    parser.add_argument("--deadline", type=float, default=0.15)
    args = parser.parse_args()

    if args.config is not None:
        resolved = load_iterative_config(args.config, args.model)
        if args.check:
            printable = {
                "status": "ok",
                "config": str(resolved["config_path"]),
                "config_sha256": resolved["config_sha256"],
                "graph": str(resolved["graph_path"]),
                "graph_sha256": resolved["graph_sha256"],
                "settings": resolved["settings"],
                "models": resolved["models"],
            }
            print(json.dumps(printable, ensure_ascii=False, indent=2))
            return 0
        output = args.output or default_matrix_output_path()
        summary = run_configured_benchmarks(
            args.config,
            output,
            selected_models=args.model,
        )
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return 0

    if args.model:
        parser.error("--model requires --config")
    if args.check:
        parser.error("--check requires --config")
    selector = get_selector()
    output = args.output or default_output_path(selector)
    summary = run_benchmark(
        output,
        repeats=args.repeats,
        warmups=args.warmups,
        case_count=args.case_count,
        route_seed=args.route_seed,
        graph_path=args.graph,
        case_mode=args.case_mode,
        candidate_scope=args.candidate_scope,
        context_mode=args.context_mode,
        max_steps=args.max_steps,
        deadline=args.deadline,
        selector=selector,
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
