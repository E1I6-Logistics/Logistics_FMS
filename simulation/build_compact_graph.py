"""Build an LLM-friendly compact graph from a route GeoJSON file."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from simulation.route_comparison_service import build_compact_route_graph


def route_file(name: str) -> Path:
    path = (PROJECT_ROOT / "routes" / name).resolve()
    if path.parent != (PROJECT_ROOT / "routes").resolve():
        raise ValueError("그래프 파일은 routes 폴더 안에서만 선택할 수 있습니다.")
    return path


def main() -> int:
    parser = argparse.ArgumentParser(description="GeoJSON을 LLM용 Compact Graph로 변환합니다.")
    parser.add_argument("--source", default="test.geojson", help="원본 routes 파일")
    parser.add_argument(
        "--output",
        default="test_compact_graph.geojson",
        help="생성할 routes 파일",
    )
    args = parser.parse_args()

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


if __name__ == "__main__":
    raise SystemExit(main())
