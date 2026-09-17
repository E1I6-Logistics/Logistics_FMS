# 타입 힌트 지연 평가 기능 사용
from __future__ import annotations

# 원본 GeoJSON 유지용 깊은 복사 기능 사용
import copy
# Route Graph GeoJSON 파일 파싱 기능 사용
import json
from typing import (
    Any,
    Union,
)

from ..config import ROUTE_GRAPH_PATH


# 숫자 및 문자열 Node ID 모두 지원
NodeId = Union[int, str]


# ============================================================
# GeoJSON Load
# ============================================================

# Route Graph GeoJSON 파일 로드 및 형식 검증 기능
def load_route_graph() -> dict[str, Any]:

    # Route Graph 파일 존재 여부 확인
    if not ROUTE_GRAPH_PATH.exists():

        raise FileNotFoundError(
            f"Route Graph 파일 없음: {ROUTE_GRAPH_PATH}"
        )

    # Route Graph JSON 파일 열기 및 파싱
    with ROUTE_GRAPH_PATH.open(
        "r",
        encoding="utf-8",
    ) as file:
        graph = json.load(file)

    # GeoJSON FeatureCollection 형식 검증
    if graph.get("type") != "FeatureCollection":

        raise ValueError(
            "Route Graph는 GeoJSON "
            "FeatureCollection 형식이어야 합니다."
        )

    return graph


# ============================================================
# Node ID key 통일
# ============================================================

# Node ID 비교용 문자열 Key 변환 기능
def _id_key(
    value: Any,
) -> str:

    return str(value)


# ============================================================
# Node Lookup 생성
# ============================================================

# Node ID 기준 Point Feature Lookup 생성 기능
def node_lookup(
    graph: dict[str, Any] | None = None,
) -> dict[str, dict[str, Any]]:

    source = (
        graph
        or load_route_graph()
    )

    nodes: dict[
        str,
        dict[str, Any],
    ] = {}

    for feature in source.get(
        "features",
        [],
    ):

        geometry = (
            feature.get("geometry")
            or {}
        )

        properties = (
            feature.get("properties")
            or {}
        )

        # Point Geometry만 Node로 사용
        if geometry.get("type") != "Point":
            continue

        coordinates = geometry.get(
            "coordinates"
        )

        node_id = properties.get(
            "id"
        )

        if node_id is None:
            continue

        if not isinstance(
            coordinates,
            list,
        ):
            continue

        if len(coordinates) < 2:
            continue

        # Node ID 기준 Feature 저장
        nodes[
            _id_key(node_id)
        ] = feature

    return nodes


# ============================================================
# 특정 Node
# ============================================================

# 특정 Node 정보 조회 기능
def get_node(
    node_id: NodeId,
) -> dict[str, Any]:

    graph = load_route_graph()

    nodes = node_lookup(
        graph
    )

    feature = nodes.get(
        _id_key(node_id)
    )

    if feature is None:

        raise KeyError(
            f"존재하지 않는 route node: {node_id}"
        )

    coordinates = (
        feature["geometry"]["coordinates"]
    )

    properties = (
        feature.get("properties", {})
    )

    return {

        "id": properties.get(
            "id"
        ),

        "x": float(
            coordinates[0]
        ),

        "y": float(
            coordinates[1]
        ),

        "frame": properties.get(
            "frame",
            "map",
        ),

        "properties": properties,
    }


# ============================================================
# 전체 Node
# ============================================================

# 전체 Node 정보 목록 생성 기능
def list_nodes() -> list[dict[str, Any]]:

    graph = load_route_graph()

    result: list[
        dict[str, Any]
    ] = []

    for feature in node_lookup(
        graph
    ).values():

        coordinates = (
            feature["geometry"]["coordinates"]
        )

        properties = (
            feature.get(
                "properties",
                {},
            )
        )

        result.append(
            {
                "id": properties.get(
                    "id"
                ),

                "x": float(
                    coordinates[0]
                ),

                "y": float(
                    coordinates[1]
                ),

                "frame": properties.get(
                    "frame",
                    "map",
                ),

                "properties": properties,
            }
        )

    # 숫자 Node ID 우선 정렬 기준 생성 기능
    def sort_key(
        node: dict[str, Any],
    ):

        value = node["id"]

        try:

            return (
                0,
                int(value),
            )

        except (
            TypeError,
            ValueError,
        ):

            return (
                1,
                str(value),
            )

    return sorted(
        result,
        key=sort_key,
    )


# ============================================================
# Frontend 렌더링용 GeoJSON 생성
# ============================================================

# Frontend 렌더링용 GeoJSON 복사본 생성 기능
def build_renderable_geojson() -> dict[str, Any]:

    """
    현재 test.geojson에는 일부 MultiLineString feature에
    coordinates가 없고,

        startid
        endid

    만 존재한다.

    따라서 원본 GeoJSON 파일은 수정하지 않고,
    API response용 복사본에서

        start node 좌표
        end node 좌표

    를 찾아 coordinates를 생성한다.
    """

    graph = load_route_graph()

    # 원본 Route Graph 보호를 위한 깊은 복사
    renderable = copy.deepcopy(
        graph
    )

    nodes = node_lookup(
        graph
    )

    for feature in renderable.get(
        "features",
        [],
    ):

        geometry = (
            feature.get("geometry")
            or {}
        )

        geometry_type = geometry.get(
            "type"
        )

        # LineString 및 MultiLineString Edge만 처리
        if geometry_type not in (
            "LineString",
            "MultiLineString",
        ):
            continue

        # 이미 좌표가 있으면 그대로 사용
        coordinates = geometry.get(
            "coordinates"
        )

        # 기존 Edge 좌표가 있으면 그대로 사용
        if coordinates:
            continue

        properties = (
            feature.get("properties")
            or {}
        )

        start_id = properties.get(
            "startid"
        )

        end_id = properties.get(
            "endid"
        )

        if (
            start_id is None
            or end_id is None
        ):
            continue

        # Edge 시작 Node 정보 조회
        start_feature = nodes.get(
            _id_key(start_id)
        )

        # Edge 종료 Node 정보 조회
        end_feature = nodes.get(
            _id_key(end_id)
        )

        if (
            start_feature is None
            or end_feature is None
        ):
            continue

        start_coord = (
            start_feature[
                "geometry"
            ][
                "coordinates"
            ][:2]
        )

        end_coord = (
            end_feature[
                "geometry"
            ][
                "coordinates"
            ][:2]
        )

        # MultiLineString 형식 좌표 생성
        if geometry_type == "MultiLineString":

            geometry["coordinates"] = [
                [
                    start_coord,
                    end_coord,
                ]
            ]

        else:

            geometry["coordinates"] = [
                start_coord,
                end_coord,
            ]

    return renderable


# ============================================================
# Graph Summary
# ============================================================

# Route Graph Node 및 Edge 요약 정보 생성 기능
def graph_summary() -> dict[str, Any]:

    graph = load_route_graph()

    nodes = 0

    edges = 0

    edges_without_coordinates = 0

    for feature in graph.get(
        "features",
        [],
    ):

        geometry = (
            feature.get("geometry")
            or {}
        )

        geometry_type = geometry.get(
            "type"
        )

        # Point Feature 개수 기준 Node 수 계산
        if geometry_type == "Point":

            nodes += 1

        # LineString 계열 Feature 개수 기준 Edge 수 계산
        elif geometry_type in (
            "LineString",
            "MultiLineString",
        ):

            edges += 1

            if not geometry.get(
                "coordinates"
            ):

                edges_without_coordinates += 1

    return {

        "name": graph.get(
            "name",
            "graph",
        ),

        "nodes": nodes,

        "edges": edges,

        "edges_without_coordinates":
            edges_without_coordinates,

        "source":
            ROUTE_GRAPH_PATH.name,
    }