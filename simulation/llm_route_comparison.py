"""Compare code and LLM routes and record reproducible evaluation metrics."""

from __future__ import annotations

import json
import math
import os
from datetime import datetime, timezone
from pathlib import Path
from time import monotonic

from simulation.route_comparison_service import (
    compare_path_metrics,
    validate_and_calculate_path_distance,
)

if __package__:
    from .llm_providers import get_provider
    from .llm_providers.base import LLMPathProvider
    from .summarize_llm_comparisons import write_summary
else:
    from llm_providers import get_provider
    from llm_providers.base import LLMPathProvider
    from summarize_llm_comparisons import write_summary


SIMULATION_DIR = Path(__file__).resolve().parent
LLM_RESULT_PATH = SIMULATION_DIR / "llm_route_comparisons.jsonl"
LLM_SUMMARY_PATH = SIMULATION_DIR / "llm_route_summary.json"
ROUTE_DIR = Path(__file__).resolve().parents[1] / "routes"


def resolve_llm_route_graph_path(value: str | Path | None = None) -> Path:
    """Resolve a raw or compact LLM graph under the routes directory."""
    selected = Path(value or os.getenv("LLM_ROUTE_GRAPH", "test.geojson"))
    if not selected.is_absolute():
        selected = ROUTE_DIR / selected
    selected = selected.resolve()
    if selected.parent != ROUTE_DIR.resolve():
        raise ValueError("LLM 입력 그래프는 routes 폴더의 파일만 선택할 수 있습니다.")
    if not selected.is_file():
        raise FileNotFoundError(f"LLM 입력 그래프를 찾을 수 없습니다: {selected}")
    return selected

ROUTE_GRAPH_PATH = resolve_llm_route_graph_path()


def request_llm_shortest_path(raw_graph, start_id, target_id):
    """Ask the provider selected by LLM_PROVIDER for one route."""
    provider = get_provider()
    return provider.compute_shortest_path(raw_graph, start_id, target_id)


def _input_metrics(raw_graph: dict, start_id: int, target_id: int) -> dict:
    payload = {
        "route_graph": raw_graph,
        "start_node": start_id,
        "target_node": target_id,
        "required_path_endpoints": {"first": start_id, "last": target_id},
    }
    prompt = (
        LLMPathProvider.COMPACT_INSTRUCTIONS
        if raw_graph.get("type") == "CompactRouteGraph"
        else LLMPathProvider.INSTRUCTIONS
    )
    input_text = prompt + json.dumps(
        payload, ensure_ascii=False, separators=(",", ":")
    )
    character_count = len(input_text)
    return {
        "input_character_count": character_count,
        "estimated_input_tokens": math.ceil(character_count / 4),
    }


def _is_timeout_error(error: Exception) -> bool:
    error_name = type(error).__name__.lower()
    error_text = str(error).lower()
    return (
        isinstance(error, TimeoutError)
        or "timeout" in error_name
        or "timed out" in error_text
    )


def _append_result(result: dict) -> None:
    with LLM_RESULT_PATH.open("a", encoding="utf-8") as result_file:
        result_file.write(json.dumps(result, ensure_ascii=False) + "\n")
    write_summary(LLM_RESULT_PATH, LLM_SUMMARY_PATH)


def compare_path_with_llm(
    points,
    edges,
    start_id,
    target_id,
    baseline_path,
    route_graph_path: str | Path | None = None,
    max_attempts: int | None = None,
):
    """Run the LLM harness and save both successful and failed evaluations."""
    selected_graph_path = (
        resolve_llm_route_graph_path(route_graph_path)
        if route_graph_path is not None
        else ROUTE_GRAPH_PATH
    )
    raw_graph = json.loads(selected_graph_path.read_text(encoding="utf-8"))
    baseline_path, baseline_distance = validate_and_calculate_path_distance(
        points, edges, baseline_path, start_id, target_id
    )
    print(baseline_path, "   |   ", baseline_distance)

    provider_key = os.getenv("LLM_PROVIDER", "openai").strip().lower()
    model_env_name = f"{provider_key.upper()}_MODEL"
    attempt_limit = max_attempts or int(os.getenv("LLM_MAX_ATTEMPTS", "1"))
    if attempt_limit < 1:
        raise ValueError("LLM_MAX_ATTEMPTS는 1 이상이어야 합니다.")

    attempts: list[dict] = []
    llm_answer: dict | None = None
    llm_path: list[int] | None = None
    llm_distance: float | None = None
    last_error: Exception | None = None

    for attempt_number in range(1, attempt_limit + 1):
        started = monotonic()
        attempt = {
            "attempt": attempt_number,
            "json_response_success": False,
            "valid_path": False,
            "timed_out": False,
        }
        try:
            llm_answer = request_llm_shortest_path(raw_graph, start_id, target_id)
            attempt["json_response_success"] = isinstance(llm_answer, dict)
            llm_path, llm_distance = validate_and_calculate_path_distance(
                points,
                edges,
                llm_answer["path"],
                start_id,
                target_id,
            )
            attempt["valid_path"] = True
        except Exception as error:
            last_error = error
            attempt["timed_out"] = _is_timeout_error(error)
            attempt["error_type"] = type(error).__name__
            attempt["error_message"] = str(error)
        finally:
            attempt["response_time_seconds"] = round(monotonic() - started, 6)
            attempts.append(attempt)

        if attempt["valid_path"]:
            break

    successful_attempt = next(
        (item["attempt"] for item in attempts if item["valid_path"]), None
    )
    comparison = None
    if llm_path is not None and llm_distance is not None:
        comparison = compare_path_metrics(
            baseline_path, baseline_distance, llm_path, llm_distance
        )

    total_response_time = sum(item["response_time_seconds"] for item in attempts)
    realtime_deadline = float(
        os.getenv("PATH_DECISION_DEADLINE_SECONDS", "0.15")
    )
    if realtime_deadline <= 0:
        raise ValueError("PATH_DECISION_DEADLINE_SECONDS는 0보다 커야 합니다.")
    metrics = {
        "json_response_success": any(
            item["json_response_success"] for item in attempts
        ),
        "valid_path": successful_attempt is not None,
        "shortest_path_match": comparison["same_path"] if comparison else False,
        "shortest_distance_match": comparison["same_distance"] if comparison else False,
        "absolute_distance_error": (
            abs(comparison["distance_difference"]) if comparison else None
        ),
        "response_time_seconds": round(total_response_time, 6),
        "realtime_deadline_seconds": realtime_deadline,
        # 유효한 경로가 제한 시간 안에 도착해야 실시간 기준을 충족한다.
        "meets_realtime_deadline": (
            successful_attempt is not None
            and total_response_time <= realtime_deadline
        ),
        "timed_out": any(item["timed_out"] for item in attempts),
        "first_attempt_success": successful_attempt == 1,
        "retry_success": successful_attempt is not None and successful_attempt > 1,
        "attempt_count": len(attempts),
        **_input_metrics(raw_graph, start_id, target_id),
    }

    result = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "status": "success" if successful_attempt is not None else "failed",
        "provider": provider_key,
        "model": os.getenv(model_env_name),
        "prompt_strategy": (
            "compact-dijkstra"
            if raw_graph.get("type") == "CompactRouteGraph"
            else "geojson-dijkstra"
        ),
        "input": {
            "start_node": start_id,
            "target_node": target_id,
            "route_graph_file": selected_graph_path.name,
            "route_graph": raw_graph,
        },
        "baseline": {
            "path": baseline_path,
            "recalculated_total_distance": baseline_distance,
        },
        "llm": {
            # 검증에 실패해도 모델이 실제 반환한 경로를 디버깅할 수 있게 보존한다.
            "path": (
                llm_answer.get("path")
                if isinstance(llm_answer, dict)
                else None
            ),
            "reported_total_distance": (
                llm_answer.get("reported_total_distance")
                if isinstance(llm_answer, dict)
                else None
            ),
            "recalculated_total_distance": llm_distance,
        },
        "comparison": comparison,
        "metrics": metrics,
        "attempts": attempts,
    }
    if last_error is not None and successful_attempt is None:
        result["error"] = {
            "type": type(last_error).__name__,
            "message": str(last_error),
        }

    _append_result(result)
    return result
