"""Run one code-vs-LLM route comparison without starting ROS or Zenoh."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from time import monotonic

# Allow `python simulation/run_llm_comparison.py` from the repository root.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.app.config import ROUTE_GRAPH_PATH as CONFIGURED_GRAPH_PATH
from backend.app.services.route_graph import load_route_graph, node_lookup
from backend.app.services.route_planner import plan_route
from simulation.llm_route_comparison import (
    LLM_RESULT_PATH,
    ROUTE_GRAPH_PATH as COMPARISON_GRAPH_PATH,
    compare_path_with_llm,
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


def main() -> int:
    parser = argparse.ArgumentParser(
        description="코드 최단 경로와 선택한 LLM 경로를 한 번 비교합니다."
    )
    parser.add_argument("--start", type=int, default=2, help="시작 노드 ID (기본값: 2)")
    parser.add_argument("--goal", type=int, default=10, help="도착 노드 ID (기본값: 10)")
    parser.add_argument(
        "--dry-run", action="store_true", help="LLM 호출 없이 코드 경로만 확인"
    )
    args = parser.parse_args()

    try:
        # The comparison currently reads test.geojson directly; prevent mixed graphs.
        if CONFIGURED_GRAPH_PATH.resolve() != COMPARISON_GRAPH_PATH.resolve():
            raise ValueError(
                "FMS_ROUTE_GRAPH와 LLM 비교 입력 그래프가 다릅니다. "
                "현재 비교는 routes/test.geojson만 지원합니다."
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
            points, edges, args.start, args.goal, baseline
        )
        print(f"응답 완료: {monotonic() - started:.1f}초", flush=True)
        print(f"LLM 경로: {result['llm']['path']}")
        print(f"경로 일치: {result['comparison']['same_path']}")
        print(f"거리 일치: {result['comparison']['same_distance']}")
        print(f"결과 파일: {LLM_RESULT_PATH}")
        return 0
    except Exception as exc:
        print(f"비교 실패 ({type(exc).__name__}): {exc}", file=sys.stderr, flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
