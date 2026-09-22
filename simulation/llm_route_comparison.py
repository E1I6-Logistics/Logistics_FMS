"""
============================================================
# LLM 경로 비교 기능 (플러그인 구조 버전)
============================================================

기존 코드 대비 바뀐 부분은 request_llm_shortest_path() 하나뿐이다.
build_edge_weight_lookup(), validate_and_calculate_path_distance()는
원본 그대로이며, compare_path_with_llm()도 로직은 동일하고
결과에 provider 이름만 추가로 기록한다.

모델·벤더를 바꾸려면 이 파일을 건드릴 필요가 없다 — 환경변수만 바꾸면 됨:
    LLM_PROVIDER=openai|anthropic|ollama
    OPENAI_MODEL / ANTHROPIC_MODEL / OLLAMA_MODEL

mock_fleet.py 쪽 통합 코드(#4. 기존 build_robot_states()에 호출 코드만 추가)는
전혀 수정할 필요가 없다 — compare_path_with_llm()의 시그니처가 그대로이기 때문이다.
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

# [LLM 추가] 경로 비교 결과를 DB 대신 JSONL 파일로 누적 저장
LLM_RESULT_PATH = Path(__file__).resolve().parent / "llm_route_comparisons.jsonl"

# mock_fleet.py와 동일한 원본 Route Graph를 사용한다.
ROUTE_GRAPH_PATH = Path(__file__).resolve().parents[1] / "routes" / "test.geojson"


def build_edge_weight_lookup(points, edges):
    """
    기존 shortest_path()와 동일한 방식으로
    각 방향성 edge의 실제 가중치를 계산한다.

    cost > 0 : GeoJSON의 cost 사용
    cost == 0: 두 노드 좌표의 직선거리 사용

    ※ 원본 코드에서 변경 없음.
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

    LLM이 반환한 거리값은 여기에서 사용하지 않는다.

    ※ 원본 코드에서 변경 없음 — 어떤 provider(OpenAI/Anthropic/Ollama)가
      path를 만들었든 동일한 기준으로 검증한다.
    """

    if not isinstance(path, list) or not path:
        raise ValueError("경로가 비어 있거나 list 형식이 아닙니다.")

    # LLM이 문자열 형태의 node id를 반환해도 정수로 변환한다.
    normalized_path = [int(node_id) for node_id in path]

    if normalized_path[0] != start_id:
        raise ValueError(f"시작 노드 불일치: " f"{normalized_path[0]} != {start_id}")

    if normalized_path[-1] != target_id:
        raise ValueError(f"도착 노드 불일치: " f"{normalized_path[-1]} != {target_id}")

    for node_id in normalized_path:
        if node_id not in points:
            raise ValueError(f"존재하지 않는 노드입니다: {node_id}")

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
            raise ValueError(f"존재하지 않는 방향성 edge입니다: " f"{start} -> {end}")

        total_distance += edge_weights[edge_key]

    return normalized_path, total_distance


def request_llm_shortest_path(raw_graph, start_id, target_id):
    """
    [변경됨] 기존에는 OpenAI를 직접 호출했지만,
    이제 LLM_PROVIDER 환경변수가 가리키는 플러그인을 통해 호출한다.

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
    기존 shortest_path() 결과와 LLM 결과를 비교하고
    JSONL 파일에 한 줄씩 저장한다.

    ※ 원본 대비 바뀐 점: 결과에 "provider"(어떤 벤더였는지) 필드를 추가했다.
      5종 모델을 번갈아 테스트할 때 이게 없으면 나중에 결과를 구분할 수 없다.
    """

    # LLM에 전달할 원본 GeoJSON을 다시 읽는다.
    with ROUTE_GRAPH_PATH.open(
        "r",
        encoding="utf-8",
    ) as route_file:
        raw_graph = json.load(route_file)

    # 기존 알고리즘의 path도 동일한 방식으로 거리를 계산한다.
    baseline_path, baseline_distance = validate_and_calculate_path_distance(
        points,
        edges,
        baseline_path,
        start_id,
        target_id,
    )

    # 원본 그래프와 동일한 시작/도착 노드를 LLM에 전달한다.
    llm_answer = request_llm_shortest_path(
        raw_graph,
        start_id,
        target_id,
    )

    # LLM이 반환한 path를 검증하고 거리를 직접 재계산한다.
    llm_path, llm_recalculated_distance = validate_and_calculate_path_distance(
        points,
        edges,
        llm_answer["path"],
        start_id,
        target_id,
    )

    provider_key = os.getenv("LLM_PROVIDER", "openai").lower()
    model_env_name = f"{provider_key.upper()}_MODEL"

    result = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        # [추가] 어떤 벤더였는지 반드시 남긴다 — 5종 비교 시 필수
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
            "recalculated_total_distance": (baseline_distance),
        },
        "llm": {
            "path": llm_path,
            # LLM이 직접 말한 값으로 비교하지 않는다.
            "reported_total_distance": (llm_answer["reported_total_distance"]),
            # 실제 비교에는 로컬에서 재계산한 값만 사용한다.
            "recalculated_total_distance": (llm_recalculated_distance),
        },
        "comparison": {
            # 노드 순서가 완전히 같은지 비교한다.
            "same_path": (baseline_path == llm_path),
            # 부동소수점 오차를 고려해 거리를 비교한다.
            "same_distance": math.isclose(
                baseline_distance,
                llm_recalculated_distance,
                rel_tol=1e-9,
                abs_tol=1e-9,
            ),
            # LLM 경로가 기준 경로보다 얼마나 길거나 짧은지 기록한다.
            "distance_difference": (llm_recalculated_distance - baseline_distance),
        },
    }

    # DB 대신 JSON Lines 형식으로 실행 결과를 누적한다.
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
