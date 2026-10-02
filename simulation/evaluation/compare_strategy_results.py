"""경로 생성 전략과 Laya/Kev 후보 선택 결과를 한 표로 모은다."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from statistics import mean, median
from typing import Any


def _spec(value: str) -> tuple[str, Path]:
    """명령행의 LABEL=DIRECTORY 값을 표시명과 결과 경로로 분리한다."""
    try:
        label, directory = value.split("=", 1)
    except ValueError as error:
        raise argparse.ArgumentTypeError("LABEL=DIRECTORY 형식이어야 합니다") from error
    if not label or not directory:
        raise argparse.ArgumentTypeError("LABEL과 DIRECTORY가 모두 필요합니다")
    return label, Path(directory)


def _load(path: Path) -> Any:
    """벤치마크가 생성한 JSON 파일을 UTF-8로 읽는다."""
    return json.loads(path.read_text(encoding="utf-8"))


def _generation_rows(label: str, directory: Path) -> list[dict[str, Any]]:
    """각 생성 전략의 모델별 정확도와 지연시간을 비교 행으로 바꾼다."""
    summary = _load(directory / "summary.json")
    manifest = _load(directory / "manifest.json")
    return [
        {
            "label": label,
            "task_type": "path_generation",
            "experiment_mode": manifest.get("experiment_mode", "V1_DIRECT"),
            "model": row["model"],
            "trial_count": row["trial_count"],
            "accuracy": row["shortest_path_match_rate"],
            "valid_result_rate": row["valid_path_rate"],
            "median_seconds": row["median_response_time_seconds"],
            "realtime_met_rate": row["realtime_deadline_success_rate"],
            "output_budget_exhaustion_rate": row.get("output_budget_exhaustion_rate"),
            "think_control_ignored_rate": row.get("think_control_ignored_rate"),
            "mean_api_call_count": row.get("mean_api_call_count"),
            "mean_input_prompt_eval_count": row.get(
                "mean_input_prompt_eval_count"
            ),
            "mean_output_eval_count": row.get("mean_output_eval_count"),
            "mean_total_eval_count": row.get("mean_total_eval_count"),
            "mean_retrieved_node_count": row.get("mean_retrieved_node_count"),
            "mean_retrieved_edge_count": row.get("mean_retrieved_edge_count"),
            "ground_truth_path_available_rate": row.get(
                "ground_truth_path_available_rate"
            ),
            "retrieval_enabled": manifest.get("retrieval", {}).get(
                "enabled", False
            ),
            "comparison_scope": "five-route full-path generation",
            "directly_comparable": True,
        }
        for row in summary["models"]
    ]


def _selector_row(label: str, directory: Path) -> dict[str, Any]:
    """Laya/Kev 결과 중 shortest_path 후보 선택 사례만 별도로 집계한다."""
    summary = _load(directory / "selector_latency_summary.json")
    samples_path = directory / "selector_latency_samples.csv"
    with samples_path.open(encoding="utf-8-sig", newline="") as stream:
        samples = [
            row for row in csv.DictReader(stream)
            if row["question_type"] == "shortest_path"
        ]
    # 직관·일반 추론 문항은 생성 모델의 최단경로 시험과 관련이 없어 제외한다.
    successful = [row for row in samples if not row["error"]]
    times = [float(row["wall_seconds"]) for row in successful]
    return {
        "label": label,
        "task_type": "candidate_selection",
        "experiment_mode": "DECISION_SELECTOR",
        "model": summary.get("requested_model"),
        "trial_count": len(samples),
        "accuracy": (
            mean(row["correct"].lower() == "true" for row in samples)
            if samples else None
        ),
        "valid_result_rate": len(successful) / len(samples) if samples else None,
        "median_seconds": median(times) if times else None,
        "realtime_met_rate": mean(
            row["realtime_met"].lower() == "true" for row in samples
        ) if samples else None,
        "output_budget_exhaustion_rate": None,
        "think_control_ignored_rate": None,
        "mean_api_call_count": None,
        "mean_input_prompt_eval_count": None,
        "mean_output_eval_count": None,
        "mean_total_eval_count": None,
        "mean_retrieved_node_count": None,
        "mean_retrieved_edge_count": None,
        "ground_truth_path_available_rate": None,
        "retrieval_enabled": None,
        "comparison_scope": "shortest-path candidate selection",
        "directly_comparable": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--generation", action="append", type=_spec, default=[])
    parser.add_argument("--selector", action="append", type=_spec, default=[])
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    rows = []
    # 생성형과 판단형은 같은 CSV에 놓되 directly_comparable로 해석 범위를 표시한다.
    for label, directory in args.generation:
        rows.extend(_generation_rows(label, directory.resolve()))
    for label, directory in args.selector:
        rows.append(_selector_row(label, directory.resolve()))
    if not rows:
        parser.error("--generation 또는 --selector 결과가 하나 이상 필요합니다")
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "strategy_comparison.json").write_text(
        json.dumps({
            "note": (
                "V1/V2 생성 모델끼리는 직접 비교할 수 있다. Laya/Kev는 이미 "
                "제시된 후보를 선택하므로 생성 정확도와 같은 지표로 해석하지 않는다."
            ),
            "rows": rows,
        }, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    with (args.output / "strategy_comparison.csv").open(
        "w", encoding="utf-8-sig", newline=""
    ) as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    print(f"비교 결과: {args.output.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
