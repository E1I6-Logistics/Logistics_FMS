"""Compare route-selector latency by complexity, language, and answer position."""

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

from simulation.route_selector import get_selector
from simulation.services.route_service import (
    build_compact_route_graph,
    build_route_inputs,
    plan_route,
    validate_and_calculate_path_distance,
)

TRIALS_FILENAME = "selector_latency_trials.jsonl"
SUMMARY_FILENAME = "selector_latency_summary.json"
CSV_FILENAME = "selector_latency_samples.csv"
DEFAULT_RESULTS_DIR = ROOT / "simulation" / "benchmark_results"
ROUTE_GRAPH_PATH = ROOT / "routes" / "test_benchmark_v1.geojson"
OPTION_IDS = ("option_a", "option_b", "option_c", "option_d", "option_e")
Clock = Callable[[], float]


def _route_question_data(language: str) -> dict[str, Any]:
    """Build the route case from the same graph and validator as the simulator."""
    graph = json.loads(ROUTE_GRAPH_PATH.read_text(encoding="utf-8"))
    points, edges = build_route_inputs(graph)
    baseline = plan_route("2", "10", graph)
    correct_path = [int(node) for node in baseline["node_ids"]]
    _, correct_distance = validate_and_calculate_path_distance(
        points, edges, correct_path, 2, 10
    )
    long_path = [2, 5, 4, 6, 13, 8, 9, 10]
    _, long_distance = validate_and_calculate_path_distance(
        points, edges, long_path, 2, 10
    )
    candidates = [
        f"path={correct_path}, distance={correct_distance:.6f}",
        f"path={long_path}, distance={long_distance:.6f}",
        "path=[2,10]",
        "path=[2,5,6,10]",
        "path=[2,5,4,13,6,10]",
    ]
    state = {
        "start_node": 2,
        "target_node": 10,
        "route_graph": build_compact_route_graph(graph, ROUTE_GRAPH_PATH.name),
    }
    if language == "ko":
        instructions = (
            "방향성 간선으로 모두 연결된 후보 중 간선 weight 합이 가장 작은 "
            "경로를 선택하세요."
        )
    else:
        instructions = (
            "Select the candidate whose nodes are connected by directed edges and "
            "whose sum of edge weights is the smallest."
        )
    return {
        "state": state,
        "instructions": instructions,
        "answers": candidates,
        "correct_answer": candidates[0],
    }


def _base_questions() -> list[dict[str, Any]]:
    return [
        {
            "type": "intuitive",
            "language": "ko",
            "label": "한국어 직관 질문",
            "state": "상자에 붙은 라벨의 색상은 파란색입니다.",
            "instructions": "상자 라벨의 색상을 선택하세요.",
            "answers": ["파란색", "빨간색", "초록색", "노란색", "검은색"],
            "correct_answer": "파란색",
        },
        {
            "type": "intuitive",
            "language": "en",
            "label": "English intuitive question",
            "state": "The label attached to the box is blue.",
            "instructions": "Choose the color of the label on the box.",
            "answers": ["Blue", "Red", "Green", "Yellow", "Black"],
            "correct_answer": "Blue",
        },
        {
            "type": "reasoning",
            "language": "ko",
            "label": "한국어 사고 질문",
            "state": (
                "민수는 영희보다 키가 큽니다. 영희는 철수보다 키가 큽니다. "
                "철수는 지수보다 키가 큽니다. 지수는 준호보다 키가 큽니다."
            ),
            "instructions": "다섯 사람 중 키가 가장 큰 사람을 선택하세요.",
            "answers": ["민수", "영희", "철수", "지수", "준호"],
            "correct_answer": "민수",
        },
        {
            "type": "reasoning",
            "language": "en",
            "label": "English reasoning question",
            "state": (
                "Alice is taller than Bob. Bob is taller than Carol. "
                "Carol is taller than David. David is taller than Erin."
            ),
            "instructions": "Choose the tallest person among the five people.",
            "answers": ["Alice", "Bob", "Carol", "David", "Erin"],
            "correct_answer": "Alice",
        },
        {
            "type": "shortest_path",
            "language": "ko",
            "label": "한국어 최단거리 질문",
            **_route_question_data("ko"),
        },
        {
            "type": "shortest_path",
            "language": "en",
            "label": "English shortest-path question",
            **_route_question_data("en"),
        },
    ]


def _positioned_candidates(
    answers: list[str], correct_answer: str, answer_position: int
) -> tuple[dict[str, str], str]:
    """Place the same correct answer once at each of the five option positions."""
    distractors = [answer for answer in answers if answer != correct_answer]
    ordered_answers = distractors.copy()
    ordered_answers.insert(answer_position, correct_answer)
    candidates = dict(zip(OPTION_IDS, ordered_answers, strict=True))
    expected_choice = OPTION_IDS[answer_position]
    return candidates, expected_choice


def build_test_cases() -> tuple[dict[str, Any], ...]:
    cases = []
    for question in _base_questions():
        for position in range(len(OPTION_IDS)):
            candidates, expected_choice = _positioned_candidates(
                question["answers"], question["correct_answer"], position
            )
            cases.append(
                {
                    "id": (
                        f"{question['language']}_{question['type']}_"
                        f"position_{position + 1}"
                    ),
                    "question_type": question["type"],
                    "language": question["language"],
                    "label": question["label"],
                    "answer_position": position + 1,
                    "state": question["state"],
                    "instructions": question["instructions"],
                    "candidates": candidates,
                    "expected_choice": expected_choice,
                    "correct_answer": question["correct_answer"],
                }
            )
    return tuple(cases)


TEST_CASES = build_test_cases()


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _append_jsonl(path: Path, value: dict[str, Any]) -> None:
    with path.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(value, ensure_ascii=False) + "\n")


def _json_dump(path: Path, value: dict[str, Any]) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _percentile(values: list[float], percentile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered) - 1) * percentile
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    fraction = position - lower
    return ordered[lower] + (ordered[upper] - ordered[lower]) * fraction


def _latency_stats(values: list[float]) -> dict[str, float | int | None]:
    return {
        "count": len(values),
        "mean_seconds": mean(values) if values else None,
        "median_seconds": median(values) if values else None,
        "p95_seconds": _percentile(values, 0.95),
        "min_seconds": min(values) if values else None,
        "max_seconds": max(values) if values else None,
    }


def _summarize_trials(trials: list[dict[str, Any]]) -> dict[str, Any]:
    successful = [trial for trial in trials if trial["error"] is None]
    wall_times = [trial["wall_seconds"] for trial in successful]
    server_times = [
        trial["model_total_seconds"]
        for trial in successful
        if trial["model_total_seconds"] is not None
    ]
    eval_times = [
        trial["eval_seconds"]
        for trial in successful
        if trial["eval_seconds"] is not None
    ]
    return {
        "trial_count": len(trials),
        "successful_request_count": len(successful),
        "error_count": len(trials) - len(successful),
        "correct_count": sum(bool(trial["correct"]) for trial in trials),
        "accuracy": (
            sum(bool(trial["correct"]) for trial in trials) / len(trials)
            if trials
            else None
        ),
        "realtime_met_count": sum(bool(trial["realtime_met"]) for trial in trials),
        "realtime_met_rate": (
            sum(bool(trial["realtime_met"]) for trial in trials) / len(trials)
            if trials
            else None
        ),
        "wall_latency": _latency_stats(wall_times),
        "model_total_latency": _latency_stats(server_times),
        "model_eval_latency": _latency_stats(eval_times),
    }


def _write_csv(path: Path, trials: list[dict[str, Any]]) -> None:
    fieldnames = [
        "case_id", "question_type", "language", "answer_position", "repeat",
        "timestamp", "requested_model", "response_model", "choice",
        "expected_choice", "correct_answer", "correct", "confidence",
        "wall_seconds", "model_total_seconds", "load_seconds", "eval_seconds",
        "realtime_deadline_seconds", "realtime_met", "probabilities", "routing",
        "error",
    ]
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fieldnames)
        writer.writeheader()
        for trial in trials:
            row = {field: trial.get(field) for field in fieldnames}
            for field in ("probabilities", "routing"):
                row[field] = json.dumps(
                    trial.get(field), ensure_ascii=False, separators=(",", ":")
                )
            writer.writerow(row)


def run_latency_benchmark(
    output: Path,
    *,
    repeats: int = 5,
    warmups: int = 1,
    realtime_deadline_seconds: float = 0.15,
    selector: Any | None = None,
    clock: Clock = time.perf_counter,
    progress: bool = True,
) -> dict[str, Any]:
    """Measure all languages, complexities, and correct-answer positions."""
    if repeats < 1:
        raise ValueError("repeats must be at least 1")
    if warmups < 0:
        raise ValueError("warmups must be 0 or greater")
    if realtime_deadline_seconds <= 0:
        raise ValueError("realtime_deadline_seconds must be positive")

    output = output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    trials_path = output / TRIALS_FILENAME
    if trials_path.exists() and trials_path.stat().st_size:
        raise FileExistsError(f"existing trial file would be overwritten: {trials_path}")

    selector = selector or get_selector()
    started_at = _utc_now()

    # Warm each language/type once. Position variants use the already-warmed model.
    for question in _base_questions():
        candidates, _ = _positioned_candidates(
            question["answers"], question["correct_answer"], 0
        )
        for warmup in range(1, warmups + 1):
            selector.select_choice(
                question["state"], candidates, question["instructions"],
                question_id=f"warmup_{question['language']}_{question['type']}",
            )
            if progress:
                print(
                    f"{question['language']} {question['type']} "
                    f"warmup {warmup}/{warmups} complete"
                )

    trials: list[dict[str, Any]] = []
    for case in TEST_CASES:
        for repeat in range(1, repeats + 1):
            started = clock()
            try:
                result = selector.select_choice(
                    case["state"], case["candidates"], case["instructions"],
                    question_id=case["id"],
                )
                wall_seconds = clock() - started
                trial = {
                    "case_id": case["id"],
                    "question_type": case["question_type"],
                    "language": case["language"],
                    "answer_position": case["answer_position"],
                    "repeat": repeat,
                    "timestamp": _utc_now(),
                    "requested_model": selector.model,
                    "response_model": result.get("model"),
                    "choice": result.get("choice"),
                    "expected_choice": case["expected_choice"],
                    "correct_answer": case["correct_answer"],
                    "correct": result.get("choice") == case["expected_choice"],
                    "confidence": result.get("confidence"),
                    "probabilities": result.get("probabilities"),
                    "routing": result.get("routing"),
                    "wall_seconds": wall_seconds,
                    "model_total_seconds": result.get("total_duration_seconds"),
                    "load_seconds": result.get("load_duration_seconds"),
                    "eval_seconds": result.get("eval_duration_seconds"),
                    "realtime_deadline_seconds": realtime_deadline_seconds,
                    "realtime_met": wall_seconds <= realtime_deadline_seconds,
                    "error": None,
                    "raw": result.get("raw"),
                }
            except Exception as error:
                wall_seconds = clock() - started
                trial = {
                    "case_id": case["id"],
                    "question_type": case["question_type"],
                    "language": case["language"],
                    "answer_position": case["answer_position"],
                    "repeat": repeat,
                    "timestamp": _utc_now(),
                    "requested_model": getattr(selector, "model", None),
                    "response_model": None,
                    "choice": None,
                    "expected_choice": case["expected_choice"],
                    "correct_answer": case["correct_answer"],
                    "correct": False,
                    "confidence": None,
                    "probabilities": None,
                    "routing": None,
                    "wall_seconds": wall_seconds,
                    "model_total_seconds": None,
                    "load_seconds": None,
                    "eval_seconds": None,
                    "realtime_deadline_seconds": realtime_deadline_seconds,
                    "realtime_met": False,
                    "error": f"{type(error).__name__}: {error}",
                    "raw": None,
                }
            trials.append(trial)
            _append_jsonl(trials_path, trial)
            if progress:
                print(
                    f"{case['id']} {repeat:02d}/{repeats} "
                    f"choice={trial['choice']} expected={trial['expected_choice']} "
                    f"correct={trial['correct']} wall={wall_seconds:.6f}s"
                )

    groups = []
    for language in ("ko", "en"):
        for question_type in ("intuitive", "reasoning", "shortest_path"):
            grouped = [
                trial for trial in trials
                if trial["language"] == language
                and trial["question_type"] == question_type
            ]
            groups.append(
                {
                    "language": language,
                    "question_type": question_type,
                    **_summarize_trials(grouped),
                }
            )
    positions = []
    for position in range(1, len(OPTION_IDS) + 1):
        positioned = [trial for trial in trials if trial["answer_position"] == position]
        positions.append(
            {"answer_position": position, **_summarize_trials(positioned)}
        )

    summary = {
        "benchmark": "route-selector-language-position-latency-v3",
        "started_at": started_at,
        "completed_at": _utc_now(),
        "requested_model": getattr(selector, "model", None),
        "settings": {
            "question_types": 3,
            "languages": 2,
            "answer_positions": 5,
            "option_count": 5,
            "case_count": len(TEST_CASES),
            "warmups_per_language_and_type": warmups,
            "repeats_per_case": repeats,
            "expected_trial_count": len(TEST_CASES) * repeats,
            "realtime_deadline_seconds": realtime_deadline_seconds,
        },
        "overall": _summarize_trials(trials),
        "groups": groups,
        "answer_positions": positions,
    }
    _json_dump(output / SUMMARY_FILENAME, summary)
    _write_csv(output / CSV_FILENAME, trials)
    return summary


def _default_output() -> Path:
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    return DEFAULT_RESULTS_DIR / f"route-selector-v3-{timestamp}"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--repeats", type=int, default=5, help="repeats per case")
    parser.add_argument("--warmups", type=int, default=1, help="warmups per language/type")
    parser.add_argument("--deadline", type=float, default=0.15)
    args = parser.parse_args()

    selector = get_selector()
    output = args.output or _default_output()
    summary = run_latency_benchmark(
        output, repeats=args.repeats, warmups=args.warmups,
        realtime_deadline_seconds=args.deadline, selector=selector,
    )
    print(f"results: {output.resolve()}")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
