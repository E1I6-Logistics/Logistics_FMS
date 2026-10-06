"""Compare Ollama, Laya, and Kev through iterative next-node selection."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean, median
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from simulation.evaluation.device_metadata import git_metadata, selector_device_metadata
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
TRIALS_FILENAME = "selector_iterative_route_trials.jsonl"
SUMMARY_FILENAME = "selector_iterative_route_summary.json"
CSV_FILENAME = "selector_iterative_route_samples.csv"
MANIFEST_FILENAME = "manifest.json"

NEXT_NODE_INSTRUCTIONS = (
    "Select exactly one next node for the minimum-total-weight route from "
    "current_node to target_node. The selected node must be connected by one "
    "directed edge from current_node. Use the CompactAdjacencyGraph weight exactly "
    "as stored. Choose only from the supplied criteria. If available_edges "
    "is present, it is an exact lookup of outgoing edges; choose only a node "
    "listed there. Previously visited nodes may be selected again when needed "
    "to reach the target. Return only the selected criteria ID."
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


def _prepare() -> dict[str, Any]:
    config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    graph_path = ROOT / config["graph"]["path"]
    graph = json.loads(graph_path.read_text(encoding="utf-8"))
    points, edges = build_route_inputs(graph, require_stored_weight=True)
    edge_weights = build_edge_weight_lookup(points, edges)
    compact_graph = build_compact_adjacency_graph(
        graph,
        graph_path.name,
        require_stored_weight=True,
    )

    print("=============\n")
    print(compact_graph)

    cases = []
    for configured in config["cases"]:
        start, target = int(configured["start"]), int(configured["goal"])
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
    return {
        "graph_path": graph_path,
        "graph": graph,
        "compact_graph": compact_graph,
        "points": points,
        "edges": edges,
        "edge_weights": edge_weights,
        "nodes": sorted(points),
        "cases": cases,
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
        if candidate_scope == "neighbors":
            pool = {
                end
                for (edge_start, end) in prepared["edge_weights"]
                if edge_start == current and end not in visited
            }
        else:
            pool = {node for node in prepared["nodes"] if node != current}
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
    api_call_count = 0
    accumulated_distance = 0.0
    error: str | None = None
    failed_step: int | None = None
    invalid_edge_count = 0
    revisit_count = 0
    started = time.perf_counter()
    step_limit = max_steps if max_steps is not None else len(prepared["nodes"]) * 2
    if step_limit < 1:
        raise ValueError("max_steps must be positive")

    for step_index in range(step_limit):
        if current == target:
            break
        # 현재 Node의 outgoing Edge를 한 번만 정확 조회한다. 이전에 방문한
        # Node도 후보에 유지해 우회·복귀 후 Target에 도착할 수 있게 한다.
        # 무한 순환은 step_limit에서 중단하고 결과에 오류로 기록한다.
        neighbor_edges = get_available_edges(
            prepared["compact_graph"], current
        )
        if candidate_scope == "neighbors":
            candidate_nodes = [int(edge["node"]) for edge in neighbor_edges]
        else:
            candidate_nodes = [node for node in prepared["nodes"] if node != current]
        if not candidate_nodes:
            error = f"이동 가능한 후보 노드가 없습니다: current={current}"
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
            if revisited:
                revisit_count += 1
            steps.append(
                {
                    "step": step_index + 1,
                    "current_node": current,
                    "candidate_scope": candidate_scope,
                    "context_mode": context_mode,
                    "available_edges": available_edges,
                    "candidates": candidates,
                    "candidate_count": 1,
                    "choice": f"node_{next_node}",
                    "next_node": next_node,
                    "edge_weight": weight,
                    "forced_step": True,
                    "model_called": False,
                    "accepted": True,
                    "revisited": revisited,
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
            path.append(next_node)
            current = next_node
            continue

        state = {
            "route_graph": prepared["compact_graph"],
            "current_node": current,
            "target_node": target,
            "visited_nodes": path,
            "accumulated_distance": accumulated_distance,
        }
        if available_edges is not None:
            state["available_edges"] = available_edges
        step_started = time.perf_counter()
        step_record: dict[str, Any] = {
            "step": step_index + 1,
            "current_node": current,
            "candidate_scope": candidate_scope,
            "context_mode": context_mode,
            "available_edges": available_edges,
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
            if edge_key not in prepared["edge_weights"]:
                invalid_edge_count += 1
                raise ValueError(f"존재하지 않는 방향성 edge: {current} -> {next_node}")
            weight = prepared["edge_weights"][edge_key]
            step_record.update(edge_weight=weight, accepted=True, error=None)
            steps.append(step_record)
            accumulated_distance += weight
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
        "valid_path": valid_path,
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
        "exact_path_match_count": sum(bool(row["exact_path_match"]) for row in rows),
        "distance_match_count": sum(bool(row["distance_match"]) for row in rows),
        "invalid_edge_count": sum(row["invalid_edge_count"] for row in rows),
        "revisit_count": sum(row["revisit_count"] for row in rows),
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


def run_benchmark(
    output: Path,
    *,
    repeats: int = 5,
    warmups: int = 1,
    candidate_scope: str = "neighbors",
    context_mode: str = "neighbor_context",
    max_steps: int | None = None,
    deadline: float = 0.15,
    selector: Any | None = None,
    progress: bool = True,
) -> dict[str, Any]:
    if repeats < 1 or warmups < 0:
        raise ValueError("repeats must be positive and warmups must be non-negative")
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

    prepared = _prepare()
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
            "revisit_policy": "allowed_until_target_or_max_steps",
            "realtime_deadline_seconds": deadline,
            "python_role": "state storage, validation, and deterministic single-candidate transition",
            "single_candidate_policy": "forced_step_without_model_call",
            "selector_max_length": getattr(selector, "max_length", None),
            "selector_head_max_length": getattr(selector, "head_max_length", None),
        },
        "device": selector_device_metadata(selector),
    }
    _json_dump(output / MANIFEST_FILENAME, manifest)

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
        "random_baseline_path_probability",
        "candidate_scope", "context_mode", "failed_step",
        "invalid_edge_count", "revisit_count",
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
            for field in ("expected_path", "path", "steps"):
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


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--repeats", type=int, default=5)
    parser.add_argument("--warmups", type=int, default=1)
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
    summary = run_benchmark(
        args.output,
        repeats=args.repeats,
        warmups=args.warmups,
        candidate_scope=args.candidate_scope,
        context_mode=args.context_mode,
        max_steps=args.max_steps,
        deadline=args.deadline,
        selector=get_selector(),
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
