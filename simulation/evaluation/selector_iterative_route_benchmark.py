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
    build_compact_route_graph,
    build_route_inputs,
    build_edge_weight_lookup,
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
    "directed edge from current_node. Use edge weight exactly as stored. All graph "
    "nodes are listed as criteria, but invalid non-neighbors must not be selected. "
    "Do not select a visited node. Return only the selected criteria ID."
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
    compact_graph = build_compact_route_graph(
        graph,
        graph_path.name,
        require_stored_weight=True,
    )
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


def _run_route(
    selector: Any,
    prepared: dict[str, Any],
    case: dict[str, Any],
) -> dict[str, Any]:
    start, target = case["start"], case["target"]
    current = start
    path = [start]
    steps: list[dict[str, Any]] = []
    api_call_count = 0
    accumulated_distance = 0.0
    error: str | None = None
    started = time.perf_counter()

    for step_index in range(len(prepared["nodes"]) - 1):
        if current == target:
            break
        candidates = {
            f"node_{node}": f"Node {node}"
            for node in prepared["nodes"]
            if node != current
        }
        state = {
            "route_graph": prepared["compact_graph"],
            "current_node": current,
            "target_node": target,
            "visited_nodes": path,
            "accumulated_distance": accumulated_distance,
        }
        step_started = time.perf_counter()
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
            if not choice.startswith("node_"):
                raise ValueError(f"잘못된 next-node 응답: {choice!r}")
            next_node = int(choice.removeprefix("node_"))
            if next_node in path:
                raise ValueError(f"이미 방문한 노드 재선택: {next_node}")
            edge_key = (current, next_node)
            if edge_key not in prepared["edge_weights"]:
                raise ValueError(f"존재하지 않는 방향성 edge: {current} -> {next_node}")
            weight = prepared["edge_weights"][edge_key]
            steps.append(
                {
                    "step": step_index + 1,
                    "current_node": current,
                    "choice": choice,
                    "next_node": next_node,
                    "edge_weight": weight,
                    "confidence": result.get("confidence"),
                    "probabilities": result.get("probabilities"),
                    # Laya의 토큰 수와 입력 잘림 여부를 단계별로 보존한다.
                    "usage": result.get("usage"),
                    "state_truncated": result.get("state_truncated"),
                    "wall_seconds": step_wall,
                    "model_total_seconds": result.get("total_duration_seconds"),
                    "eval_seconds": result.get("eval_duration_seconds"),
                }
            )
            accumulated_distance += weight
            path.append(next_node)
            current = next_node
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"
            break

    if error is None and current != target:
        error = f"최대 단계 초과: target={target}, current={current}"

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
    truncation_values = [step.get("state_truncated") for step in steps]
    state_truncated_count = sum(value is True for value in truncation_values)
    state_truncation_reported_count = sum(
        isinstance(value, bool) for value in truncation_values
    )
    truncation_reporting_complete = (
        bool(steps) and state_truncation_reported_count == len(steps)
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
        "wall_seconds": wall_seconds,
        "state_truncated_count": state_truncated_count,
        "state_truncation_reported_count": state_truncation_reported_count,
        "state_truncation_reporting_complete": truncation_reporting_complete,
        "full_graph_input_preserved": full_graph_input_preserved,
        "model_total_seconds": sum(
            float(step["model_total_seconds"])
            for step in steps
            if step["model_total_seconds"] is not None
        ),
        "error": error,
    }


def _summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    completed = [row for row in rows if row["error"] is None]
    return {
        "trial_count": len(rows),
        "completed_count": len(completed),
        "error_count": len(rows) - len(completed),
        "valid_path_count": sum(bool(row["valid_path"]) for row in rows),
        "exact_path_match_count": sum(bool(row["exact_path_match"]) for row in rows),
        "distance_match_count": sum(bool(row["distance_match"]) for row in rows),
        "state_truncated_trial_count": sum(
            row["state_truncated_count"] > 0 for row in rows
        ),
        "state_truncation_unreported_trial_count": sum(
            not row["state_truncation_reporting_complete"] for row in rows
        ),
        "full_graph_input_preserved_count": sum(
            row["full_graph_input_preserved"] is True for row in rows
        ),
        "exact_path_accuracy": (
            sum(bool(row["exact_path_match"]) for row in rows) / len(rows)
            if rows else None
        ),
        "mean_api_call_count": (
            mean(row["api_call_count"] for row in rows) if rows else None
        ),
        "wall_latency": _stats([row["wall_seconds"] for row in completed]),
        "model_total_latency": _stats(
            [row["model_total_seconds"] for row in completed]
        ),
    }


def run_benchmark(
    output: Path,
    *,
    repeats: int = 5,
    warmups: int = 1,
    selector: Any | None = None,
    progress: bool = True,
) -> dict[str, Any]:
    if repeats < 1 or warmups < 0:
        raise ValueError("repeats must be positive and warmups must be non-negative")
    output = output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    trials_path = output / TRIALS_FILENAME
    if trials_path.exists() and trials_path.stat().st_size:
        raise FileExistsError(f"existing trial file would be overwritten: {trials_path}")

    prepared = _prepare()
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
            "model_input_format": "CompactRouteGraph",
            "node_count": len(prepared["nodes"]),
        },
        "settings": {
            "repeats_per_case": repeats,
            "warmups": warmups,
            "case_count": len(prepared["cases"]),
            "expected_trial_count": len(prepared["cases"]) * repeats,
            "questions_per_api_request": 1,
            "candidate_scope": "all_nodes_except_current",
            "max_steps": len(prepared["nodes"]) - 1,
            "python_role": "state storage and validation only",
            "selector_max_length": getattr(selector, "max_length", None),
        },
        "device": selector_device_metadata(selector),
    }
    _json_dump(output / MANIFEST_FILENAME, manifest)

    for warmup in range(1, warmups + 1):
        _run_route(selector, prepared, prepared["cases"][0])
        if progress:
            print(f"warmup {warmup}/{warmups} complete")

    rows: list[dict[str, Any]] = []
    last_result = None
    for case in prepared["cases"]:
        for repeat in range(1, repeats + 1):
            result = _run_route(selector, prepared, case)
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
        "recalculated_distance", "api_call_count", "valid_path",
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
    args = parser.parse_args()
    summary = run_benchmark(
        args.output,
        repeats=args.repeats,
        warmups=args.warmups,
        selector=get_selector(),
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
