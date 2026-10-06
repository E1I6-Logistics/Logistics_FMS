"""Evaluate one-call selection over every valid simple route for each V1 pair."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import random
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
    plan_route,
    validate_and_calculate_path_distance,
)

GRAPH_PATH = ROOT / "routes" / "test.geojson"
CONFIG_PATH = ROOT / "simulation" / "evaluation" / "route_generation_benchmark.json"
RESULTS_ROOT = ROOT / "simulation" / "benchmark_results"
MANIFEST_FILENAME = "manifest.json"
TRIALS_FILENAME = "selector_all_routes_trials.jsonl"
SUMMARY_FILENAME = "selector_all_routes_summary.json"
CSV_FILENAME = "selector_all_routes_samples.csv"

INSTRUCTIONS = {
    "ko": (
        "모든 선택지는 시작 노드에서 목표 노드까지 이동 가능한 단순 방향성 "
        "경로입니다. route_graph의 저장된 Edge weight를 사용해 각 후보의 총 "
        "weight를 계산하고 가장 작은 경로 하나를 선택하세요. 좌표로 거리를 "
        "다시 계산하지 말고 선택지 순서나 ID를 근거로 사용하지 마세요."
    ),
    "en": (
        "Every option is a valid simple directed path from start_node to target_node. "
        "Use the stored edge weights in route_graph to calculate each candidate's "
        "total weight and select the minimum-weight path. Do not recalculate weights "
        "from coordinates or infer the answer from option order or ID."
    ),
}


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _json_dump(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _append_jsonl(path: Path, value: dict[str, Any]) -> None:
    with path.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(value, ensure_ascii=False) + "\n")


def _percentile(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered) - 1) * fraction
    lower, upper = math.floor(position), math.ceil(position)
    if lower == upper:
        return ordered[lower]
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def _latency(values: list[float]) -> dict[str, Any]:
    return {
        "count": len(values),
        "mean_seconds": mean(values) if values else None,
        "median_seconds": median(values) if values else None,
        "p95_seconds": _percentile(values, 0.95),
        "min_seconds": min(values) if values else None,
        "max_seconds": max(values) if values else None,
    }


def enumerate_all_simple_paths(
    graph: dict[str, Any], start: int, target: int
) -> list[tuple[list[int], float]]:
    """Return every directed path without repeated nodes, ordered only internally."""
    points, edges = build_route_inputs(graph, require_stored_weight=True)
    adjacency: dict[int, list[tuple[int, float]]] = {node: [] for node in points}
    for edge_start, edge_end, weight in edges:
        adjacency[edge_start].append((edge_end, float(weight)))
    for neighbors in adjacency.values():
        neighbors.sort()

    routes: list[tuple[list[int], float]] = []

    def visit(node: int, path: list[int], distance: float) -> None:
        if node == target:
            routes.append((path.copy(), distance))
            return
        for neighbor, weight in adjacency[node]:
            if neighbor not in path:
                visit(neighbor, [*path, neighbor], distance + weight)

    visit(start, [start], 0.0)
    routes.sort(key=lambda item: (item[1], item[0]))
    if not routes:
        raise ValueError(f"유효한 단순 경로가 없습니다: {start} -> {target}")
    return routes


def _prepare() -> dict[str, Any]:
    graph_bytes = GRAPH_PATH.read_bytes()
    graph = json.loads(graph_bytes)
    config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    points, edges = build_route_inputs(graph, require_stored_weight=True)
    compact_graph = build_compact_route_graph(
        graph, GRAPH_PATH.name, require_stored_weight=True
    )
    cases = []
    for configured in config["cases"]:
        start, target = int(configured["start"]), int(configured["goal"])
        routes = enumerate_all_simple_paths(graph, start, target)
        baseline = plan_route(
            str(start), str(target), graph, require_stored_weight=True
        )
        expected_path = [int(node) for node in baseline["node_ids"]]
        expected_distance = float(baseline["cost"])
        if routes[0][0] != expected_path or not math.isclose(
            routes[0][1], expected_distance, rel_tol=1e-12, abs_tol=1e-12
        ):
            raise ValueError(f"전체 경로 정렬과 Ground Truth 불일치: {start}->{target}")
        cases.append(
            {
                "start": start,
                "target": target,
                "routes": routes,
                "expected_path": expected_path,
                "expected_distance": expected_distance,
            }
        )
    return {
        "graph": graph,
        "graph_sha256": hashlib.sha256(graph_bytes).hexdigest(),
        "compact_graph": compact_graph,
        "points": points,
        "edges": edges,
        "cases": cases,
    }


def _build_request(
    prepared: dict[str, Any], case: dict[str, Any], language: str, seed: int
) -> dict[str, Any]:
    shuffled = [(path.copy(), distance) for path, distance in case["routes"]]
    random.Random(seed).shuffle(shuffled)
    candidates: dict[str, str] = {}
    candidate_paths: dict[str, list[int]] = {}
    expected_choice = None
    for index, (path, _distance) in enumerate(shuffled, start=1):
        choice_id = f"route_{index:03d}"
        candidates[choice_id] = f"path={path}"
        candidate_paths[choice_id] = path
        if path == case["expected_path"]:
            expected_choice = choice_id
    if expected_choice is None:
        raise RuntimeError("섞은 후보에서 Ground Truth를 찾지 못했습니다.")
    return {
        "state": {
            "task": "select_shortest_route",
            "start_node": case["start"],
            "target_node": case["target"],
            "route_graph": prepared["compact_graph"],
        },
        "instructions": INSTRUCTIONS[language],
        "candidates": candidates,
        "candidate_paths": candidate_paths,
        "expected_choice": expected_choice,
    }


def _option_diagnostics(
    usage: Any, question_id: str, candidate_count: int, selector_name: str
) -> tuple[int | None, bool | None]:
    if selector_name != "laya" or not isinstance(usage, dict):
        return None, None
    options = usage.get("options")
    if not isinstance(options, dict) or question_id not in options:
        # Laya는 선택지가 잘렸을 때만 usage.options에 해당 질문을 기록한다.
        return candidate_count, True
    report = options[question_id]
    distinct = report.get("distinct") if isinstance(report, dict) else None
    return distinct, distinct == candidate_count if isinstance(distinct, int) else None


def _run_trial(
    selector: Any,
    prepared: dict[str, Any],
    case: dict[str, Any],
    language: str,
    repeat: int,
    seed: int,
    deadline: float,
) -> dict[str, Any]:
    order_seed = seed + case["start"] * 100_000 + case["target"] * 1_000 + repeat
    if language == "en":
        order_seed += 10_000_000
    request = _build_request(prepared, case, language, order_seed)
    question_id = f"{language}_all_routes_{case['start']}_to_{case['target']}_{repeat}"
    input_character_count = len(json.dumps(
        {
            "state": request["state"],
            "instructions": request["instructions"],
            "criteria": request["candidates"],
        },
        ensure_ascii=False,
        separators=(",", ":"),
    ))
    started = time.perf_counter()
    try:
        result = selector.select_choice(
            request["state"],
            request["candidates"],
            request["instructions"],
            question_id=question_id,
        )
        wall_seconds = time.perf_counter() - started
        choice = str(result.get("choice", ""))
        selected_path = request["candidate_paths"].get(choice)
        if selected_path is None:
            raise ValueError(f"후보에 없는 선택: {choice!r}")
        validated_path, selected_distance = validate_and_calculate_path_distance(
            prepared["points"], prepared["edges"], selected_path,
            case["start"], case["target"],
        )
        probabilities = dict(result.get("probabilities") or {})
        usage = result.get("usage")
        input_tokens = None
        if isinstance(usage, dict):
            input_tokens = usage.get("input_tokens", usage.get("prompt_tokens"))
        distinct_count, options_complete = _option_diagnostics(
            usage, question_id, len(request["candidates"]), selector.name
        )
        return {
            "choice": choice,
            "selected_path": validated_path,
            "selected_distance": selected_distance,
            "correct": choice == request["expected_choice"],
            "confidence": result.get("confidence"),
            "answer_confidence": result.get("answer_confidence"),
            "probabilities": probabilities,
            "probability_count": len(probabilities),
            "probability_complete": (
                len(probabilities) == len(request["candidates"])
                if probabilities else None
            ),
            "usage": usage,
            "input_character_count": input_character_count,
            "input_tokens": input_tokens,
            "state_truncated": result.get("state_truncated"),
            "distinct_option_count": distinct_count,
            "options_complete": options_complete,
            "wall_seconds": wall_seconds,
            "model_total_seconds": result.get("total_duration_seconds"),
            "eval_seconds": result.get("eval_duration_seconds"),
            "realtime_met": wall_seconds <= deadline,
            "response_model": result.get("model"),
            "runtime": result.get("runtime"),
            "raw": result.get("raw"),
            "error": None,
            "request": request,
            "question_id": question_id,
            "candidate_order_seed": order_seed,
        }
    except Exception as error:
        return {
            "choice": None,
            "selected_path": None,
            "selected_distance": None,
            "correct": False,
            "confidence": None,
            "answer_confidence": None,
            "probabilities": None,
            "probability_count": 0,
            "probability_complete": None,
            "usage": None,
            "input_character_count": input_character_count,
            "input_tokens": None,
            "state_truncated": None,
            "distinct_option_count": None,
            "options_complete": None,
            "wall_seconds": time.perf_counter() - started,
            "model_total_seconds": None,
            "eval_seconds": None,
            "realtime_met": False,
            "response_model": None,
            "runtime": None,
            "raw": None,
            "error": f"{type(error).__name__}: {error}",
            "request": request,
            "question_id": question_id,
            "candidate_order_seed": order_seed,
        }


def _summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    successful = [row for row in rows if row["error"] is None]
    return {
        "trial_count": len(rows),
        "successful_request_count": len(successful),
        "error_count": len(rows) - len(successful),
        "correct_count": sum(row["correct"] is True for row in rows),
        "accuracy": (
            sum(row["correct"] is True for row in rows) / len(rows) if rows else None
        ),
        "random_baseline_accuracy": (
            mean(1 / row["candidate_count"] for row in rows) if rows else None
        ),
        "state_truncated_count": sum(
            row.get("state_truncated") is True for row in successful
        ),
        "state_truncation_unreported_count": sum(
            not isinstance(row.get("state_truncated"), bool) for row in successful
        ),
        "option_completeness_unreported_count": sum(
            row.get("selector_name") == "laya"
            and row.get("options_complete") is None
            for row in successful
        ),
        "incomplete_option_trial_count": sum(
            row.get("options_complete") is False for row in successful
        ),
        "incomplete_probability_trial_count": sum(
            row.get("probability_complete") is False for row in successful
        ),
        "wall_latency": _latency([row["wall_seconds"] for row in successful]),
        "model_total_latency": _latency([
            row["model_total_seconds"] for row in successful
            if row["model_total_seconds"] is not None
        ]),
    }


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    fields = [
        "timestamp", "selector_name", "requested_model", "response_model",
        "language", "start_node", "target_node", "repeat",
        "candidate_count", "candidate_order_seed", "expected_choice", "choice",
        "expected_path", "selected_path", "expected_distance", "selected_distance",
        "correct", "confidence", "answer_confidence", "probability_count",
        "probability_complete", "distinct_option_count", "options_complete",
        "state_truncated", "wall_seconds", "model_total_seconds", "eval_seconds",
        "realtime_met", "input_character_count", "input_tokens",
        "candidate_paths", "usage", "probabilities", "error",
    ]
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        for source in rows:
            row = {field: source.get(field) for field in fields}
            for field in (
                "expected_path", "selected_path", "candidate_paths", "usage", "probabilities"
            ):
                row[field] = json.dumps(source.get(field), ensure_ascii=False, separators=(",", ":"))
            writer.writerow(row)


def run_benchmark(
    output: Path,
    *,
    repeats: int = 5,
    warmups: int = 1,
    seed: int = 20260928,
    deadline: float = 0.15,
    selector: Any | None = None,
    progress: bool = True,
) -> dict[str, Any]:
    if repeats < 1 or warmups < 0:
        raise ValueError("repeats must be positive and warmups non-negative")
    if deadline <= 0:
        raise ValueError("deadline must be positive")
    output = output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    trials_path = output / TRIALS_FILENAME
    if trials_path.exists() and trials_path.stat().st_size:
        raise FileExistsError(f"existing trial file would be overwritten: {trials_path}")

    prepared = _prepare()
    selector = selector or get_selector()
    selector_name = getattr(selector, "name", selector.__class__.__name__)
    settings = {
        "candidate_generation": "all_simple_paths",
        "candidate_content": "path_only_without_distance",
        "languages": ["ko", "en"],
        "case_count": len(prepared["cases"]),
        "repeats_per_case_and_language": repeats,
        "warmups_per_language": warmups,
        "expected_trial_count": len(prepared["cases"]) * 2 * repeats,
        "seed": seed,
        "realtime_deadline_seconds": deadline,
        "selector_max_length": getattr(selector, "max_length", None),
        "selector_head_max_length": getattr(selector, "head_max_length", None),
    }
    manifest = {
        "benchmark": "route-selector-all-simple-routes-v1",
        "status": "running",
        "started_at": _utc_now(),
        "source": git_metadata(ROOT),
        "selector_name": selector_name,
        "requested_model": getattr(selector, "model", None),
        "graph": {
            "path": str(GRAPH_PATH.relative_to(ROOT)),
            "sha256": prepared["graph_sha256"],
            "format": "CompactRouteGraph",
            "weight_rule": "GeoJSON properties.weight exactly",
        },
        "instructions_sha256": {
            language: hashlib.sha256(text.encode("utf-8")).hexdigest()
            for language, text in INSTRUCTIONS.items()
        },
        "routes": [
            {
                "start_node": case["start"],
                "target_node": case["target"],
                "candidate_count": len(case["routes"]),
                "random_baseline_accuracy": 1 / len(case["routes"]),
            }
            for case in prepared["cases"]
        ],
        "settings": settings,
        "device": selector_device_metadata(selector),
    }
    _json_dump(output / MANIFEST_FILENAME, manifest)

    for language_index, language in enumerate(("ko", "en")):
        for warmup in range(1, warmups + 1):
            _run_trial(
                selector, prepared, prepared["cases"][0], language,
                -warmup, seed + language_index * 10_000_000, deadline,
            )
            if progress:
                print(f"{language} warmup {warmup}/{warmups} complete")

    rows: list[dict[str, Any]] = []
    last_result = None
    for case in prepared["cases"]:
        for language in ("ko", "en"):
            for repeat in range(1, repeats + 1):
                result = _run_trial(
                    selector, prepared, case, language, repeat, seed, deadline
                )
                last_result = result
                row = {
                    "timestamp": _utc_now(),
                    "selector_name": selector_name,
                    "requested_model": getattr(selector, "model", None),
                    "response_model": result["response_model"],
                    "language": language,
                    "start_node": case["start"],
                    "target_node": case["target"],
                    "repeat": repeat,
                    "candidate_count": len(case["routes"]),
                    "candidate_paths": result["request"]["candidate_paths"],
                    "expected_choice": result["request"]["expected_choice"],
                    "expected_path": case["expected_path"],
                    "expected_distance": case["expected_distance"],
                    **{key: value for key, value in result.items() if key != "request"},
                }
                rows.append(row)
                _append_jsonl(trials_path, row)
                if progress:
                    print(
                        f"{language} {case['start']}->{case['target']} "
                        f"{repeat}/{repeats} candidates={row['candidate_count']} "
                        f"choice={row['choice']} correct={row['correct']} "
                        f"error={row['error']}"
                    )

    route_groups = []
    for case in prepared["cases"]:
        selected = [
            row for row in rows
            if row["start_node"] == case["start"]
            and row["target_node"] == case["target"]
        ]
        route_groups.append({
            "start_node": case["start"],
            "target_node": case["target"],
            "candidate_count": len(case["routes"]),
            **_summarize(selected),
        })
    language_groups = [
        {"language": language, **_summarize([row for row in rows if row["language"] == language])}
        for language in ("ko", "en")
    ]
    summary = {
        "benchmark": manifest["benchmark"],
        "completed_at": _utc_now(),
        "selector_name": selector_name,
        "requested_model": getattr(selector, "model", None),
        "device": selector_device_metadata(selector, last_result),
        "settings": settings,
        "overall": _summarize(rows),
        "languages": language_groups,
        "routes": route_groups,
    }
    _json_dump(output / SUMMARY_FILENAME, summary)
    _write_csv(output / CSV_FILENAME, rows)
    manifest.update(
        status="complete",
        completed_at=_utc_now(),
        completed_trial_count=len(rows),
        device=summary["device"],
        output_files=[MANIFEST_FILENAME, TRIALS_FILENAME, SUMMARY_FILENAME, CSV_FILENAME],
    )
    _json_dump(output / MANIFEST_FILENAME, manifest)
    release = getattr(selector, "release", None)
    if callable(release):
        release()
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--repeats", type=int, default=5)
    parser.add_argument("--warmups", type=int, default=1)
    parser.add_argument("--seed", type=int, default=20260928)
    parser.add_argument("--deadline", type=float, default=0.15)
    args = parser.parse_args()
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    output = args.output or RESULTS_ROOT / f"selector-all-routes-{timestamp}"
    summary = run_benchmark(
        output,
        repeats=args.repeats,
        warmups=args.warmups,
        seed=args.seed,
        deadline=args.deadline,
    )
    print(f"results: {output.resolve()}")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
