"""LLM 경로 비교 JSONL을 읽어 모델·프롬프트별 누적 지표를 만든다.

입력은 ``llm_route_comparison.py``가 실행마다 한 줄씩 저장한 JSONL이며,
출력은 실험 조건별 성공률과 평균값을 담은 하나의 JSON 파일이다.
"""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean


def _metric_value(record: dict, field: str):
    """한 실행 기록에서 지표를 읽고 이전 결과 형식도 보정한다."""
    metrics = record["metrics"]

    # 실시간 기준 필드가 추가되기 전에 저장된 결과도 다시 집계할 수 있도록,
    # 유효 경로 여부와 응답 시간을 사용해 0.15초 충족 여부를 재계산한다.
    if field == "meets_realtime_deadline" and field not in metrics:
        deadline = metrics.get("realtime_deadline_seconds", 0.15)
        return (
            bool(metrics.get("valid_path"))
            and metrics.get("response_time_seconds", float("inf")) <= deadline
        )
    return metrics.get(field)


def _rate(records: list[dict], field: str) -> float:
    """True인 실행 수를 전체 실행 수로 나누어 0~1 비율로 반환한다."""
    return sum(bool(_metric_value(item, field)) for item in records) / len(records)


def summarize(records: list[dict]) -> dict:
    """실행 기록을 동일한 실험 조건끼리 묶어 비율과 평균을 계산한다."""
    # metrics가 없는 예전 JSONL 행은 현재 지표 구조로 비교할 수 없으므로
    # 집계에서는 제외하되, 몇 건을 제외했는지는 최종 결과에 남긴다.
    legacy_record_count = sum(
        not isinstance(record.get("metrics"), dict) for record in records
    )
    records = [
        record for record in records if isinstance(record.get("metrics"), dict)
    ]
    groups: dict[tuple, list[dict]] = defaultdict(list)
    for record in records:
        # 모델만 같아도 프롬프트, 입력 그래프, 실시간 기준이 다르면 별도 실험이다.
        # 따라서 아래 다섯 값을 하나의 그룹 키로 사용한다.
        key = (
            record.get("provider"),
            record.get("model"),
            record.get("prompt_strategy"),
            record.get("input", {}).get("route_graph_file"),
            record.get("metrics", {}).get("realtime_deadline_seconds", 0.15),
        )
        groups[key].append(record)

    summaries = []
    for (provider, model, prompt_strategy, graph_file, realtime_deadline), items in sorted(
        groups.items(), key=lambda pair: tuple(str(value) for value in pair[0])
    ):
        # 유효 경로가 나온 경우에만 거리 오차가 존재한다. 실패 결과의 None은
        # 평균 계산에서 제외하고, 계산 가능한 값이 하나도 없으면 None을 남긴다.
        distance_errors = [
            item["metrics"]["absolute_distance_error"]
            for item in items
            if item["metrics"].get("absolute_distance_error") is not None
        ]
        # 성공률 계열은 0~1 값이고, 시간·입력 크기 계열은 산술 평균이다.
        summaries.append({
            "provider": provider,
            "model": model,
            "prompt_strategy": prompt_strategy,
            "route_graph_file": graph_file,
            "run_count": len(items),
            "json_response_success_rate": _rate(items, "json_response_success"),
            "valid_path_rate": _rate(items, "valid_path"),
            "shortest_path_match_rate": _rate(items, "shortest_path_match"),
            "shortest_distance_match_rate": _rate(items, "shortest_distance_match"),
            "mean_absolute_distance_error": (
                mean(distance_errors) if distance_errors else None
            ),
            "mean_response_time_seconds": mean(
                item["metrics"]["response_time_seconds"] for item in items
            ),
            "realtime_deadline_seconds": realtime_deadline,
            "realtime_deadline_success_rate": _rate(
                items, "meets_realtime_deadline"
            ),
            "timeout_rate": _rate(items, "timed_out"),
            "first_attempt_success_rate": _rate(items, "first_attempt_success"),
            "retry_success_rate": _rate(items, "retry_success"),
            "mean_input_character_count": mean(
                item["metrics"]["input_character_count"] for item in items
            ),
            "mean_estimated_input_tokens": mean(
                item["metrics"]["estimated_input_tokens"] for item in items
            ),
        })

    # generated_at은 집계 파일이 언제 갱신됐는지 확인하기 위한 UTC 시각이다.
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "total_run_count": len(records),
        "ignored_legacy_record_count": legacy_record_count,
        "groups": summaries,
    }


def write_summary(result_path: Path, output_path: Path) -> dict:
    """JSONL 파일을 읽고 집계 결과를 JSON 파일로 저장한다."""
    # 빈 줄은 JSONL 레코드가 아니므로 건너뛴다.
    records = [
        json.loads(line)
        for line in result_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    summary = summarize(records)
    output_path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return summary


def main() -> int:
    """기본 결과 파일을 집계하거나 CLI에서 지정한 경로를 처리한다."""
    simulation_dir = Path(__file__).resolve().parent
    parser = argparse.ArgumentParser(description="LLM 경로 비교 결과를 집계합니다.")
    parser.add_argument(
        "--input",
        type=Path,
        default=simulation_dir / "llm_route_comparisons.jsonl",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=simulation_dir / "llm_route_summary.json",
    )
    args = parser.parse_args()
    # 파일 저장 후 같은 내용을 터미널에도 출력해 즉시 확인할 수 있게 한다.
    summary = write_summary(args.input, args.output)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"요약 파일: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
