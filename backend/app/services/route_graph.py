from __future__ import annotations

import copy
import json
from typing import (
    Any,
    Union,
)

from ..config import ROUTE_GRAPH_PATH


NodeId = Union[int, str]


# ============================================================
# GeoJSON Load
# ============================================================

def load_route_graph() -> dict[str, Any]:

    if not ROUTE_GRAPH_PATH.exists():

        raise FileNotFoundError(
            f"Route Graph 파일 없음: {ROUTE_GRAPH_PATH}"
        )

    with ROUTE_GRAPH_PATH.open(
        "r",
        encoding="utf-8",
    ) as file:

        graph = json.load(file)

    if graph.get("type") != "FeatureCollection":

        raise ValueError(
            "Route Graph는 GeoJSON "
            "FeatureCollection 형식이어야 합니다."
        )

    return graph


# ============================================================
# Node ID key 통일
# ============================================================

def _id_key(
    value: Any,
) -> str:

    return str(value)


# ============================================================
# Node Lookup 생성
# ============================================================

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

        nodes[
            _id_key(node_id)
        ] = feature

    return nodes


# ============================================================
# 특정 Node
# ============================================================

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

        if geometry_type not in (
            "LineString",
            "MultiLineString",
        ):
            continue

        # 이미 좌표가 있으면 그대로 사용
        coordinates = geometry.get(
            "coordinates"
        )

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

        start_feature = nodes.get(
            _id_key(start_id)
        )

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

        if geometry_type == "Point":

            nodes += 1

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