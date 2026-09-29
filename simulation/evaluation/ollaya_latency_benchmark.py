"""Compare Ollaya Laya latency across three decision complexities."""

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

from simulation.route_selector.ollaya_laya_selector import OllayaLayaSelector

TRIALS_FILENAME = "ollaya_laya_latency_trials.jsonl"
SUMMARY_FILENAME = "ollaya_laya_latency_summary.json"
CSV_FILENAME = "ollaya_laya_latency_samples.csv"
DEFAULT_RESULTS_DIR = ROOT / "simulation" / "benchmark_results"
Clock = Callable[[], float]

# All cases use the same choice API. Only the state and decision complexity differ.
TEST_CASES = (
    {
        "id": "intuitive",
        "label": "생각이 거의 필요 없는 직관 질문",
        "state": "상자에 붙은 라벨의 색상은 파란색입니다.",
        "instructions": "상자 라벨의 색상을 선택하세요.",
        "candidates": {
            "blue": "파란색",
            "red": "빨간색",
        },
        "expected_choice": "blue",
    },
    {
        "id": "reasoning",
        "label": "여러 조건을 연결하는 사고 질문",
        "state": (
            "민수는 영희보다 키가 큽니다. "
            "영희는 철수보다 키가 큽니다."
        ),
        "instructions": "세 사람 중 키가 가장 큰 사람을 선택하세요.",
        "candidates": {
            "minsu": "민수",
            "younghee": "영희",
            "cheolsu": "철수",
        },
        "expected_choice": "minsu",
    },
    {
        "id": "shortest_path",
        "label": "최단거리 경로 선택 질문",
        "state": {
            "start_node": 2,
            "target_node": 10,
            "rule": "연속된 방향성 간선을 따라 이동하고 거리 합이 가장 작은 경로를 선택한다.",
        },
        "instructions": "유효하며 총거리가 가장 짧은 경로를 선택하세요.",
        "candidates": {
            "route_a": "path=[2,5,4,6,13,8,9,10], distance=3.033652",
            "route_b": "path=[2,5,4,6,10], distance=1.592143",
        },
        "expected_choice": "route_b",
    },
)


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


def _write_csv(path: Path, trials: list[dict[str, Any]]) -> None:
    fieldnames = [
        "case_id",
        "case_label",
        "repeat",
        "timestamp",
        "requested_model",
        "response_model",
        "choice",
        "expected_choice",
        "correct",
        "confidence",
        "wall_seconds",
        "ollaya_total_seconds",
        "load_seconds",
        "eval_seconds",
        "realtime_deadline_seconds",
        "realtime_met",
        "probabilities",
        "routing",
        "error",
    ]
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fieldnames)
        writer.writeheader()
        for trial in trials:
            row = {field: trial.get(field) for field in fieldnames}
            row["probabilities"] = json.dumps(
                trial.get("probabilities"), ensure_ascii=False, separators=(",", ":")
            )
            row["routing"] = json.dumps(
                trial.get("routing"), ensure_ascii=False, separators=(",", ":")
            )
            writer.writerow(row)


def _summarize_trials(trials: list[dict[str, Any]]) -> dict[str, Any]:
    successful = [trial for trial in trials if trial["error"] is None]
    wall_times = [trial["wall_seconds"] for trial in successful]
    server_times = [
        trial["ollaya_total_seconds"]
        for trial in successful
        if trial["ollaya_total_seconds"] is not None
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
        "ollaya_total_latency": _latency_stats(server_times),
        "model_eval_latency": _latency_stats(eval_times),
    }


def run_latency_benchmark(
    output: Path,
    *,
    repeats: int = 30,
    warmups: int = 1,
    realtime_deadline_seconds: float = 0.15,
    selector: Any | None = None,
    clock: Clock = time.perf_counter,
    progress: bool = True,
) -> dict[str, Any]:
    """Run every case, then write per-case and overall latency statistics."""
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

    selector = selector or OllayaLayaSelector()
    started_at = _utc_now()

    # Warm each input form, but exclude these calls from every statistic.
    for case in TEST_CASES:
        for warmup in range(1, warmups + 1):
            selector.select_choice(
                case["state"],
                case["candidates"],
                case["instructions"],
                question_id=case["id"],
            )
            if progress:
                print(f"{case['id']} warmup {warmup}/{warmups} complete")

    trials: list[dict[str, Any]] = []
    for case in TEST_CASES:
        for repeat in range(1, repeats + 1):
            started = clock()
            try:
                result = selector.select_choice(
                    case["state"],
                    case["candidates"],
                    case["instructions"],
                    question_id=case["id"],
                )
                wall_seconds = clock() - started
                trial = {
                    "case_id": case["id"],
                    "case_label": case["label"],
                    "repeat": repeat,
                    "timestamp": _utc_now(),
                    "requested_model": selector.model,
                    "response_model": result.get("model"),
                    "choice": result.get("choice"),
                    "expected_choice": case["expected_choice"],
                    "correct": result.get("choice") == case["expected_choice"],
                    "confidence": result.get("confidence"),
                    "probabilities": result.get("probabilities"),
                    "routing": result.get("routing"),
                    "wall_seconds": wall_seconds,
                    "ollaya_total_seconds": result.get("total_duration_seconds"),
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
                    "case_label": case["label"],
                    "repeat": repeat,
                    "timestamp": _utc_now(),
                    "requested_model": getattr(selector, "model", None),
                    "response_model": None,
                    "choice": None,
                    "expected_choice": case["expected_choice"],
                    "correct": False,
                    "confidence": None,
                    "probabilities": None,
                    "routing": None,
                    "wall_seconds": wall_seconds,
                    "ollaya_total_seconds": None,
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
                    f"choice={trial['choice']} correct={trial['correct']} "
                    f"wall={wall_seconds:.6f}s realtime={trial['realtime_met']}"
                )

    case_summaries = []
    for case in TEST_CASES:
        case_trials = [trial for trial in trials if trial["case_id"] == case["id"]]
        case_summaries.append(
            {
                "case_id": case["id"],
                "case_label": case["label"],
                "state": case["state"],
                "instructions": case["instructions"],
                "candidates": case["candidates"],
                "expected_choice": case["expected_choice"],
                **_summarize_trials(case_trials),
            }
        )

    summary = {
        "benchmark": "ollaya-laya-complexity-latency-v2",
        "started_at": started_at,
        "completed_at": _utc_now(),
        "requested_model": getattr(selector, "model", None),
        "settings": {
            "case_count": len(TEST_CASES),
            "warmups_per_case": warmups,
            "repeats_per_case": repeats,
            "expected_trial_count": len(TEST_CASES) * repeats,
            "realtime_deadline_seconds": realtime_deadline_seconds,
        },
        "overall": _summarize_trials(trials),
        "cases": case_summaries,
    }
    _json_dump(output / SUMMARY_FILENAME, summary)
    _write_csv(output / CSV_FILENAME, trials)
    return summary


def _default_output() -> Path:
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    return DEFAULT_RESULTS_DIR / f"ollaya-laya-complexity-{timestamp}"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--repeats", type=int, default=30, help="repeats per case")
    parser.add_argument("--warmups", type=int, default=1, help="warmups per case")
    parser.add_argument("--deadline", type=float, default=0.15)
    parser.add_argument("--model", default=None)
    parser.add_argument("--host", default=None)
    parser.add_argument("--timeout", type=float, default=None)
    args = parser.parse_args()

    selector = OllayaLayaSelector(
        model=args.model,
        host=args.host,
        timeout_seconds=args.timeout,
    )
    output = args.output or _default_output()
    summary = run_latency_benchmark(
        output,
        repeats=args.repeats,
        warmups=args.warmups,
        realtime_deadline_seconds=args.deadline,
        selector=selector,
    )
    print(f"results: {output.resolve()}")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
