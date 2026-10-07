"""Benchmark route-selector choice, score, and noul question types."""

from __future__ import annotations

import argparse
import csv
import json
import math
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean, median
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from simulation.evaluation.device_metadata import (
    git_metadata, selector_device_metadata,
)
from simulation.evaluation.graph_path import resolve_graph_path
from simulation.route_selector import get_selector
from simulation.services.route_service import build_compact_route_graph, plan_route

TRIALS_FILENAME = "selector_question_type_trials.jsonl"
SUMMARY_FILENAME = "selector_question_type_summary.json"
CSV_FILENAME = "selector_question_type_samples.csv"
MANIFEST_FILENAME = "manifest.json"
DEFAULT_RESULTS_DIR = ROOT / "simulation" / "benchmark_results"
Clock = Callable[[], float]


def _blocked_route_state(language: str) -> dict[str, Any]:
    """Build the route-blocked question from the actual frontend map."""
    graph_path = resolve_graph_path()
    graph = json.loads(graph_path.read_text(encoding="utf-8"))
    planned = plan_route("0", "2", graph, require_stored_weight=True)
    rule = (
        "차단된 노드가 계획 경로에 포함되면 해당 경로는 사용할 수 없습니다."
        if language == "ko"
        else "A route cannot be used when it contains a blocked node."
    )
    planned_nodes = [int(node) for node in planned["node_ids"]]
    if len(planned_nodes) < 3:
        raise ValueError("차단 시험 경로에는 내부 Node가 필요합니다.")
    return {
        "start_node": 0,
        "target_node": 2,
        "planned_route": planned_nodes,
        "blocked_nodes": [planned_nodes[1]],
        "route_graph": build_compact_route_graph(
            graph, graph_path.name, require_stored_weight=True
        ),
        "rule": rule,
    }

CASES = (
    {
        "id": "ko_choice", "language": "ko", "question_type": "choice",
        "state": "창고 경고등은 빨간색입니다.",
        "instructions": "경고등의 색상을 선택하세요.",
        "criteria": {"red": "빨간색", "blue": "파란색", "green": "초록색", "yellow": "노란색", "white": "흰색"},
        "expected": "red",
    },
    {
        "id": "en_choice", "language": "en", "question_type": "choice",
        "state": "The warehouse warning light is red.",
        "instructions": "Choose the color of the warning light.",
        "criteria": {"red": "Red", "blue": "Blue", "green": "Green", "yellow": "Yellow", "white": "White"},
        "expected": "red",
    },
    {
        "id": "ko_score", "language": "ko", "question_type": "score",
        "state": "현재 작업의 긴급도는 5단계 중 가장 높은 5단계입니다.",
        "instructions": "작업의 긴급도를 평가하세요.",
        "criteria": ["매우 낮음", "낮음", "보통", "높음", "매우 높음"],
        "expected_min": 3.5, "expected_max": 4.0,
    },
    {
        "id": "en_score", "language": "en", "question_type": "score",
        "state": "The task has the highest urgency level, level 5 out of 5.",
        "instructions": "Rate the urgency of the task.",
        "criteria": ["Very low", "Low", "Medium", "High", "Very high"],
        "expected_min": 3.5, "expected_max": 4.0,
    },
    {
        "id": "ko_noul", "language": "ko", "question_type": "noul",
        "state": "3번 로봇은 장애물을 감지한 뒤 완전히 정지했습니다.",
        "instructions": "3번 로봇이 정지한 상태입니까?",
        "criteria": {"true": "정지함", "false": "움직이는 중"},
        "expected_boolean": True,
    },
    {
        "id": "en_noul", "language": "en", "question_type": "noul",
        "state": "Robot 3 detected an obstacle and came to a complete stop.",
        "instructions": "Is robot 3 stopped?",
        "criteria": {"true": "Stopped", "false": "Still moving"},
        "expected_boolean": True,
    },
    {
        "id": "ko_route_blocked_noul",
        "language": "ko",
        "question_type": "noul",
        "state": _blocked_route_state("ko"),
        "instructions": "현재 경로를 사용할 수 없는 상태입니까?",
        "criteria": {
            "true": "경로에 차단 노드가 포함되어 사용할 수 없음",
            "false": "경로에 차단 노드가 없어 사용할 수 있음",
        },
        "expected_boolean": True,
    },
    {
        "id": "en_route_blocked_noul",
        "language": "en",
        "question_type": "noul",
        "state": _blocked_route_state("en"),
        "instructions": "Is the current route unavailable?",
        "criteria": {
            "true": "The route contains a blocked node and cannot be used",
            "false": "The route contains no blocked node and can be used",
        },
        "expected_boolean": True,
    },
)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _percentile(values: list[float], percentile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered) - 1) * percentile
    lower, upper = math.floor(position), math.ceil(position)
    if lower == upper:
        return ordered[lower]
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def _stats(values: list[float]) -> dict[str, Any]:
    return {
        "count": len(values),
        "mean_seconds": mean(values) if values else None,
        "median_seconds": median(values) if values else None,
        "p95_seconds": _percentile(values, 0.95),
        "min_seconds": min(values) if values else None,
        "max_seconds": max(values) if values else None,
    }


def _summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    successful = [row for row in rows if row["error"] is None]
    return {
        "trial_count": len(rows),
        "success_count": len(successful),
        "error_count": len(rows) - len(successful),
        "correct_count": sum(bool(row["correct"]) for row in rows),
        "accuracy": sum(bool(row["correct"]) for row in rows) / len(rows) if rows else None,
        "wall_latency": _stats([row["wall_seconds"] for row in successful]),
        "model_total_latency": _stats([row["model_total_seconds"] for row in successful if row["model_total_seconds"] is not None]),
        "model_eval_latency": _stats([row["eval_seconds"] for row in successful if row["eval_seconds"] is not None]),
    }


def _call_case(selector: Any, case: dict[str, Any]) -> tuple[Any, dict[str, Any]]:
    question_type = case["question_type"]
    if question_type == "choice":
        result = selector.select_choice(
            case["state"], case["criteria"], case["instructions"], question_id=case["id"]
        )
        value = result["choice"]
        correct = value == case["expected"]
    elif question_type == "score":
        result = selector.evaluate_score(
            case["state"], case["criteria"], case["instructions"], question_id=case["id"]
        )
        value = result["score"]
        correct = case["expected_min"] <= value <= case["expected_max"]
    else:
        result = selector.evaluate_noul(
            case["state"], case["instructions"], criteria=case["criteria"], question_id=case["id"]
        )
        value = result["noul"]
        correct = (value >= 0.5) == case["expected_boolean"]
    return value, {**result, "correct": correct}


def run_question_types_benchmark(
    output: Path, *, repeats: int = 5, warmups: int = 1,
    selector: Any | None = None, clock: Clock = time.perf_counter,
    progress: bool = True,
) -> dict[str, Any]:
    if repeats < 1 or warmups < 0:
        raise ValueError("repeats must be positive and warmups must be non-negative")
    output = output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    trials_path = output / TRIALS_FILENAME
    if trials_path.exists() and trials_path.stat().st_size:
        raise FileExistsError(f"existing trial file would be overwritten: {trials_path}")
    selector = selector or get_selector()
    selector_name = getattr(selector, "name", selector.__class__.__name__)
    started_at = _utc_now()
    settings = {
        "repeats_per_case": repeats,
        "warmups_per_case": warmups,
        "case_count": len(CASES),
        "expected_trial_count": len(CASES) * repeats,
    }
    manifest = {
        "benchmark": "route-selector-question-types-v1",
        "status": "running",
        "started_at": started_at,
        "source": git_metadata(ROOT),
        "selector_name": selector_name,
        "requested_model": getattr(selector, "model", None),
        "settings": settings,
        "device": selector_device_metadata(selector),
    }
    (output / MANIFEST_FILENAME).write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    last_result = None
    for case in CASES:
        for _ in range(warmups):
            _, last_result = _call_case(selector, case)

    rows = []
    for case in CASES:
        for repeat in range(1, repeats + 1):
            started = clock()
            try:
                value, result = _call_case(selector, case)
                last_result = result
                wall_seconds = clock() - started
                row = {
                    "case_id": case["id"], "language": case["language"],
                    "question_type": case["question_type"], "repeat": repeat,
                    "timestamp": _utc_now(), "selector_name": selector_name,
                    "value": value,
                    "correct": result["correct"],
                    "confidence": result.get("confidence"),
                    "probabilities": result.get("probabilities"),
                    "legend": result.get("legend"),
                    "requested_model": selector.model,
                    "response_model": result.get("model"),
                    "wall_seconds": wall_seconds,
                    "model_total_seconds": result.get("total_duration_seconds"),
                    "load_seconds": result.get("load_duration_seconds"),
                    "eval_seconds": result.get("eval_duration_seconds"),
                    "error": None, "raw": result.get("raw"),
                }
            except Exception as error:
                wall_seconds = clock() - started
                row = {
                    "case_id": case["id"], "language": case["language"],
                    "question_type": case["question_type"], "repeat": repeat,
                    "timestamp": _utc_now(), "selector_name": selector_name,
                    "value": None, "correct": False,
                    "confidence": None, "probabilities": None, "legend": None,
                    "requested_model": getattr(selector, "model", None),
                    "response_model": None, "wall_seconds": wall_seconds,
                    "model_total_seconds": None, "load_seconds": None,
                    "eval_seconds": None,
                    "error": f"{type(error).__name__}: {error}", "raw": None,
                }
            rows.append(row)
            with trials_path.open("a", encoding="utf-8") as stream:
                stream.write(json.dumps(row, ensure_ascii=False) + "\n")
            if progress:
                print(f"{case['id']} {repeat}/{repeats} value={row['value']} correct={row['correct']} wall={wall_seconds:.6f}s")

    groups = []
    for language in ("ko", "en"):
        for question_type in ("choice", "score", "noul"):
            selected = [row for row in rows if row["language"] == language and row["question_type"] == question_type]
            groups.append({"language": language, "question_type": question_type, **_summarize(selected)})
    summary = {
        "benchmark": "route-selector-question-types-v1",
        "created_at": _utc_now(),
        "selector_name": selector_name,
        "requested_model": getattr(selector, "model", None),
        "device": selector_device_metadata(selector, last_result),
        "settings": settings,
        "overall": _summarize(rows), "groups": groups,
    }
    (output / SUMMARY_FILENAME).write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    fields = ["case_id", "language", "question_type", "repeat", "timestamp", "selector_name", "value", "correct", "confidence", "requested_model", "response_model", "wall_seconds", "model_total_seconds", "load_seconds", "eval_seconds", "probabilities", "legend", "error"]
    with (output / CSV_FILENAME).open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            exported = {field: row.get(field) for field in fields}
            for field in ("probabilities", "legend"):
                exported[field] = json.dumps(row.get(field), ensure_ascii=False, separators=(",", ":"))
            writer.writerow(exported)
    manifest.update(
        status="complete", completed_at=_utc_now(),
        completed_trial_count=len(rows), device=summary["device"],
        output_files=[
            MANIFEST_FILENAME, TRIALS_FILENAME, SUMMARY_FILENAME, CSV_FILENAME
        ],
    )
    (output / MANIFEST_FILENAME).write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--repeats", type=int, default=5)
    parser.add_argument("--warmups", type=int, default=1)
    args = parser.parse_args()
    summary = run_question_types_benchmark(
        args.output, repeats=args.repeats, warmups=args.warmups,
        selector=get_selector(),
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
