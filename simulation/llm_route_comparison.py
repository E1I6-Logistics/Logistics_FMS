"""코드 최단 경로와 LLM 계산 경로를 같은 그래프 기준으로 비교한다.

순서: GeoJSON 확보 → baseline 거리 재계산 → provider로 LLM 요청 →
LLM 경로 유효성/거리 재계산 → 두 결과 비교 → JSONL 저장.
모델 선택은 LLM_PROVIDER와 각 벤더의 *_MODEL 환경변수로 제어한다.
이 파일의 결과는 실험 기록용이며 로봇의 실제 주행 경로를 바꾸지 않는다.
"""

import json
import os
from datetime import datetime, timezone
from pathlib import Path

from backend.app.services.route_comparison_service import (
    build_edge_weight_lookup,
    compare_path_metrics,
    validate_and_calculate_path_distance,
)

# mock_fleet.py를 직접 실행하는 경우와 simulation 패키지로 실행하는 경우를
# 모두 지원한다.
if __package__:
    from .llm_providers import get_provider
else:
    from llm_providers import get_provider

# 비교 결과는 DB 의존 없이 실험별 한 줄씩 JSONL에 누적한다.
LLM_RESULT_PATH = (
    Path(__file__).resolve().parent
    / "llm_route_comparisons.jsonl"
)

# 현재 LLM 입력 그래프는 test.geojson으로 고정되어 있다. Mock Fleet의
# baseline은 FMS_ROUTE_GRAPH를 따르므로 다른 그래프를 지정하면 일치하지 않는다.
ROUTE_GRAPH_PATH = (
    Path(__file__).resolve().parents[1]
    / "routes"
    / "test.geojson"
)


def request_llm_shortest_path(raw_graph, start_id, target_id):
    """
    registry가 LLM_PROVIDER에 맞는 구현을 고른 뒤 경로 계산을 요청한다.

    provider 쪽에서 raw_graph, start_id, target_id를 그대로 받아
    기존과 동일한 스키마({"path": [...], "reported_total_distance": ...})로
    응답을 돌려준다.
    """
    provider = get_provider()
    return provider.compute_shortest_path(raw_graph, start_id, target_id)


def compare_path_with_llm(
    points,
    edges,
    start_id,
    target_id,
    baseline_path,
):
    """
    코드 baseline과 LLM 경로를 검증·비교해 JSONL 한 줄로 저장한다.

    points/edges와 baseline_path는 같은 그래프에서 나온 값이어야 한다.
    """

    # 1. LLM에는 가공하지 않은 node/edge GeoJSON을 전달한다.
    with ROUTE_GRAPH_PATH.open(
        "r",
        encoding="utf-8",
    ) as route_file:
        raw_graph = json.load(route_file)

    # 2. 코드 baseline의 거리도 로컬에서 재계산해 비교 기준을 만든다.
    baseline_path, baseline_distance = (
        validate_and_calculate_path_distance(
            points,
            edges,
            baseline_path,
            start_id,
            target_id,
        )
    )

    # 3. 같은 시작/도착 노드와 그래프를 선택한 LLM provider에 보낸다.
    llm_answer = request_llm_shortest_path(
        raw_graph,
        start_id,
        target_id,
    )

    # 4. LLM 경로가 실제 방향성 edge를 따르는지 확인하고 거리를 재계산한다.
    llm_path, llm_recalculated_distance = (
        validate_and_calculate_path_distance(
            points,
            edges,
            llm_answer["path"],
            start_id,
            target_id,
        )
    )

    provider_key = os.getenv("LLM_PROVIDER", "openai").lower()
    model_env_name = f"{provider_key.upper()}_MODEL"

    result = {
        "timestamp": datetime.now(
            timezone.utc
        ).isoformat(),

        # 여러 모델의 결과를 구분해 재현할 수 있도록 벤더/모델을 기록한다.
        "provider": provider_key,
        "model": os.getenv(model_env_name),

        "input": {
            "start_node": start_id,
            "target_node": target_id,

            # 실험 재현을 위해 당시 입력 그래프도 함께 저장한다.
            "route_graph": raw_graph,
        },

        "baseline": {
            "path": baseline_path,
            "recalculated_total_distance": (
                baseline_distance
            ),
        },

        "llm": {
            "path": llm_path,

            # LLM이 직접 말한 값으로 비교하지 않는다.
            "reported_total_distance": (
                llm_answer["reported_total_distance"]
            ),

            # 실제 비교에는 로컬에서 재계산한 값만 사용한다.
            "recalculated_total_distance": (
                llm_recalculated_distance
            ),
        },

        "comparison": compare_path_metrics(
            baseline_path,
            baseline_distance,
            llm_path,
            llm_recalculated_distance,
        ),
    }

    # 5. path·재계산 거리·일치 여부·원본 입력을 한 기록으로 저장한다.
    with LLM_RESULT_PATH.open(
        "a",
        encoding="utf-8",
    ) as result_file:
        result_file.write(
            json.dumps(
                result,
                ensure_ascii=False,
            )
            + "\n"
        )

    return result
