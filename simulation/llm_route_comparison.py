"""코드 최단 경로와 LLM 계산 경로를 같은 그래프 기준으로 비교한다.

순서: GeoJSON 확보 → baseline 거리 재계산 → provider로 LLM 요청 →
LLM 경로 유효성/거리 재계산 → 두 결과 비교 → JSONL 저장.
모델 선택은 LLM_PROVIDER와 각 벤더의 *_MODEL 환경변수로 제어한다.
이 파일의 결과는 실험 기록용이며 로봇의 실제 주행 경로를 바꾸지 않는다.
"""

import json
import math
import os
from datetime import datetime, timezone
from pathlib import Path

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


def build_edge_weight_lookup(points, edges):
    """
    코드 플래너와 같은 비용 규칙으로 방향성 edge의 가중치를 계산한다.

    cost > 0 : GeoJSON의 cost 사용
    cost == 0: 두 노드 좌표의 직선거리 사용

    검증 단계에서 baseline과 LLM 경로 모두에 적용한다.
    """

    edge_weights = {}

    for start, end, cost in edges:
        if start not in points or end not in points:
            continue

        start_x, start_y = points[start]
        end_x, end_y = points[end]

        weight = (
            cost
            if cost > 0
            else math.hypot(
                end_x - start_x,
                end_y - start_y,
            )
        )

        edge_key = (start, end)

        # 같은 방향의 edge가 여러 개라면 최소 가중치를 사용한다.
        edge_weights[edge_key] = min(
            edge_weights.get(edge_key, math.inf),
            weight,
        )

    return edge_weights


def validate_and_calculate_path_distance(
    points,
    edges,
    path,
    start_id,
    target_id,
):
    """
    전달받은 path가 실제 그래프에서 유효한지 검사하고
    총거리를 로컬 코드로 다시 계산한다.

    LLM이 반환한 거리값은 기록만 하고 비교에는 사용하지 않는다.
    모든 provider 응답에 같은 검증 기준을 적용한다.
    """

    if not isinstance(path, list) or not path:
        raise ValueError("경로가 비어 있거나 list 형식이 아닙니다.")

    # LLM이 문자열 형태의 node id를 반환해도 정수로 변환한다.
    normalized_path = [int(node_id) for node_id in path]

    if normalized_path[0] != start_id:
        raise ValueError(
            f"시작 노드 불일치: "
            f"{normalized_path[0]} != {start_id}"
        )

    if normalized_path[-1] != target_id:
        raise ValueError(
            f"도착 노드 불일치: "
            f"{normalized_path[-1]} != {target_id}"
        )

    for node_id in normalized_path:
        if node_id not in points:
            raise ValueError(
                f"존재하지 않는 노드입니다: {node_id}"
            )

    edge_weights = build_edge_weight_lookup(
        points,
        edges,
    )

    total_distance = 0.0

    # 모든 연속 노드 사이에 실제 방향성 edge가 있는지 검사한다.
    for start, end in zip(
        normalized_path,
        normalized_path[1:],
    ):
        edge_key = (start, end)

        if edge_key not in edge_weights:
            raise ValueError(
                f"존재하지 않는 방향성 edge입니다: "
                f"{start} -> {end}"
            )

        total_distance += edge_weights[edge_key]

    return normalized_path, total_distance


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

        "comparison": {
            # 노드 순서가 완전히 같은지 비교한다.
            "same_path": (
                baseline_path == llm_path
            ),

            # 부동소수점 오차를 고려해 거리를 비교한다.
            "same_distance": math.isclose(
                baseline_distance,
                llm_recalculated_distance,
                rel_tol=1e-9,
                abs_tol=1e-9,
            ),

            # LLM 경로가 기준 경로보다 얼마나 길거나 짧은지 기록한다.
            "distance_difference": (
                llm_recalculated_distance
                - baseline_distance
            ),
        },
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
