"""Command-line tools for route comparison, compact graph creation, and summaries."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from time import monotonic

from simulation.evaluation.comparison import (
    LLM_RESULT_PATH,
    LLM_SUMMARY_PATH,
    compare_path_with_llm,
    resolve_llm_route_graph_path,
)
from simulation.evaluation.summary import write_summary
from simulation.services.route_service import (
    ROUTE_GRAPH_PATH as CONFIGURED_GRAPH_PATH,
    build_compact_route_graph,
    build_route_inputs,
    load_route_graph,
    plan_route,
)


PROJECT_ROOT = Path(__file__).resolve().parents[2]
ROUTE_DIR = PROJECT_ROOT / "routes"


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


def route_file(name: str) -> Path:
    """Resolve a graph filename while preventing access outside routes/."""
    path = (ROUTE_DIR / name).resolve()
    if path.parent != ROUTE_DIR.resolve():
        raise ValueError("그래프 파일은 routes 폴더 안에서만 선택할 수 있습니다.")
    return path


def run_compare(args: argparse.Namespace) -> int:
    """Run one code-versus-LLM route comparison."""
    llm_graph_path = resolve_llm_route_graph_path(args.llm_graph)
    llm_graph = validate_selected_llm_graph(llm_graph_path)
    print(
        f"LLM 입력 그래프: {llm_graph_path.name} "
        f"({llm_graph.get('type', 'GeoJSON')})",
        flush=True,
    )

    print("경로 그래프와 코드 최단 경로를 계산합니다...", flush=True)
    graph = load_route_graph()
    points, edges = build_route_inputs(graph)
    baseline = [
        int(node_id)
        for node_id in plan_route(str(args.start), str(args.goal), graph)["node_ids"]
    ]
    print(f"코드 경로: {baseline}", flush=True)

    if args.dry_run:
        print("드라이런 완료: LLM은 호출하지 않았습니다.", flush=True)
        return 0

    provider, model = selected_provider_config()
    print(f"{provider} 모델 {model}에 요청 중...", flush=True)
    started = monotonic()
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


def run_build_compact(args: argparse.Namespace) -> int:
    """Convert a route GeoJSON file into the compact LLM input format."""
    source_path = route_file(args.source)
    output_path = route_file(args.output)
    if not source_path.is_file():
        raise FileNotFoundError(f"원본 그래프를 찾을 수 없습니다: {source_path}")

    graph = json.loads(source_path.read_text(encoding="utf-8"))
    compact = build_compact_route_graph(graph, source_path.name)
    output_path.write_text(
        json.dumps(compact, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"Compact Graph 생성 완료: {output_path}")
    print(f"노드 {len(compact['nodes'])}개, 엣지 {len(compact['edges'])}개")
    return 0


def run_summarize(args: argparse.Namespace) -> int:
    """Aggregate JSONL comparison records into a JSON summary."""
    summary = write_summary(args.input, args.output)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"요약 파일: {args.output}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="FMS 경로 모델 평가 도구")
    commands = parser.add_subparsers(dest="command", required=True)

    compare_parser = commands.add_parser(
        "compare", description="코드 최단 경로와 LLM 경로를 비교합니다."
    )
    compare_parser.add_argument("--start", type=int, required=True)
    compare_parser.add_argument("--goal", type=int, required=True)
    compare_parser.add_argument(
        "--dry-run", action="store_true", help="LLM 호출 없이 코드 경로만 확인"
    )
    compare_parser.add_argument(
        "--llm-graph",
        default=None,
        metavar="FILE",
        help="LLM에 전달할 routes 폴더의 원본 또는 Compact Graph",
    )
    compare_parser.add_argument(
        "--max-attempts",
        type=int,
        default=None,
        help="LLM 최대 시도 횟수",
    )
    compare_parser.set_defaults(handler=run_compare)

    compact_parser = commands.add_parser(
        "build-compact", description="GeoJSON을 LLM용 Compact Graph로 변환합니다."
    )
    compact_parser.add_argument("--source", default="test.geojson")
    compact_parser.add_argument(
        "--output", default="test_compact_graph.geojson"
    )
    compact_parser.set_defaults(handler=run_build_compact)

    summary_parser = commands.add_parser(
        "summarize", description="LLM 경로 비교 결과를 집계합니다."
    )
    summary_parser.add_argument("--input", type=Path, default=LLM_RESULT_PATH)
    summary_parser.add_argument("--output", type=Path, default=LLM_SUMMARY_PATH)
    summary_parser.set_defaults(handler=run_summarize)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.handler(args)
    except Exception as exc:
        print(f"실행 실패 ({type(exc).__name__}): {exc}", file=sys.stderr, flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
