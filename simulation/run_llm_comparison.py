"""Run one code-vs-LLM route comparison without starting ROS or Zenoh."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from time import monotonic

# Allow `python simulation/run_llm_comparison.py` from the repository root.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from simulation.route_graph import ROUTE_GRAPH_PATH as CONFIGURED_GRAPH_PATH
from simulation.route_graph import load_route_graph, node_lookup
from simulation.route_planner import plan_route
from simulation.llm_route_comparison import (
    LLM_RESULT_PATH,
    LLM_SUMMARY_PATH,
    compare_path_with_llm,
    resolve_llm_route_graph_path,
)


def build_route_inputs(graph: dict) -> tuple[dict[int, tuple[float, float]], list[tuple[int, int, float]]]:
    """Convert the shared GeoJSON into the comparison function's input format."""
    points = {
        int(node_id): (
            float(feature["geometry"]["coordinates"][0]),
            float(feature["geometry"]["coordinates"][1]),
        )
        for node_id, feature in node_lookup(graph).items()
    }
    edges = []
    for feature in graph.get("features", []):
        properties = feature.get("properties") or {}
        if properties.get("startid") is None or properties.get("endid") is None:
            continue
        edges.append((
            int(properties["startid"]),
            int(properties["endid"]),
            float(properties.get("cost", 0.0)),
        ))
    return points, edges


def selected_provider_config() -> tuple[str, str]:
    """Validate only the credentials needed by the selected provider."""
    provider = os.getenv("LLM_PROVIDER", "").strip().lower()
    if provider not in {"openai", "anthropic", "ollama"}:
        raise ValueError(
            "simulation/.env에 LLM_PROVIDER를 openai, anthropic 또는 ollama로 설정하세요."
        )

    model_name = f"{provider.upper()}_MODEL"
    model = os.getenv(model_name, "").strip()
    if not model:
        raise ValueError(f"simulation/.env에 {model_name}을 설정하세요.")

    if provider != "ollama":
        key_name = f"{provider.upper()}_API_KEY"
        if not os.getenv(key_name):
            raise ValueError(f"simulation/.env에 {key_name}를 설정하세요.")
    return provider, model


def validate_selected_llm_graph(graph_path: Path) -> dict:
    """Ensure the LLM input represents the same graph as the code baseline."""
    import json

    with graph_path.open("r", encoding="utf-8") as graph_file:
        llm_graph = json.load(graph_file)

    if llm_graph.get("type") == "CompactRouteGraph":
        source_name = Path(str(llm_graph.get("source_graph", ""))).name
        if source_name != CONFIGURED_GRAPH_PATH.name:
            raise ValueError(
                "Compact Graph의 source_graph와 FMS_ROUTE_GRAPH가 다릅니다: "
                f"{source_name or '(없음)'} != {CONFIGURED_GRAPH_PATH.name}"
            )
    elif graph_path.resolve() != CONFIGURED_GRAPH_PATH.resolve():
        raise ValueError(
            "원본 LLM 입력 그래프와 FMS_ROUTE_GRAPH가 다릅니다. "
            "Compact Graph를 사용할 때는 source_graph를 지정해야 합니다."
        )
    return llm_graph


def main() -> int:
    parser = argparse.ArgumentParser(
        description="코드 최단 경로와 선택한 LLM 경로를 한 번 비교합니다."
    )
    parser.add_argument("--start", type=int, default=2, help="시작 노드 ID (기본값: 2)")
    parser.add_argument("--goal", type=int, default=10, help="도착 노드 ID (기본값: 10)")
    parser.add_argument(
        "--dry-run", action="store_true", help="LLM 호출 없이 코드 경로만 확인"
    )
    parser.add_argument(
        "--llm-graph",
        default=None,
        metavar="FILE",
        help=(
            "LLM에 전달할 routes 폴더의 그래프 파일 "
            "(기본값: LLM_ROUTE_GRAPH 또는 test.geojson)"
        ),
    )
    parser.add_argument(
        "--max-attempts",
        type=int,
        default=None,
        help="LLM 최대 시도 횟수 (기본값: LLM_MAX_ATTEMPTS 또는 1)",
    )
    args = parser.parse_args()

    try:
        llm_graph_path = resolve_llm_route_graph_path(args.llm_graph)
        llm_graph = validate_selected_llm_graph(llm_graph_path)
        print(
            f"LLM 입력 그래프: {llm_graph_path.name} ({llm_graph.get('type', 'GeoJSON')})",
            flush=True,
        )

        print("경로 그래프와 코드 최단 경로를 계산합니다...", flush=True)
        graph = load_route_graph()
        points, edges = build_route_inputs(graph)
        baseline = [int(node_id) for node_id in plan_route(
            str(args.start), str(args.goal), graph
        )["node_ids"]]
        print(f"코드 경로: {baseline}", flush=True)

        if args.dry_run:
            print("드라이런 완료: LLM은 호출하지 않았습니다.", flush=True)
            return 0

        provider, model = selected_provider_config()
        print(f"{provider} 모델 {model}에 요청 중...", flush=True)
        started = monotonic()
        #LLM과 알고리즘 경로 비교
        result = compare_path_with_llm(
            points,
            edges,
            args.start,
            args.goal,
            baseline,
            route_graph_path=llm_graph_path,
            max_attempts=args.max_attempts,
        )
        print(f"응답 완료: {monotonic() - started:.1f}초", flush=True)
        print(f"상태: {result['status']}")
        print(f"LLM 경로: {result['llm']['path']}")
        print(f"경로 일치: {result['metrics']['shortest_path_match']}")
        print(f"거리 일치: {result['metrics']['shortest_distance_match']}")
        print(f"유효 경로: {result['metrics']['valid_path']}")
        print(f"시도 횟수: {result['metrics']['attempt_count']}")
        print(f"결과 파일: {LLM_RESULT_PATH}")
        print(f"요약 파일: {LLM_SUMMARY_PATH}")
        if result["status"] == "failed":
            error = result.get("error", {})
            print(
                f"비교 실패 ({error.get('type', 'LLMError')}): "
                f"{error.get('message', '유효한 경로를 받지 못했습니다.')}",
                file=sys.stderr,
                flush=True,
            )
            return 1
        return 0
    except Exception as exc:
        print(f"비교 실패 ({type(exc).__name__}): {exc}", file=sys.stderr, flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
