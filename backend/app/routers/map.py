# 타입 힌트 지연 평가 기능 사용
from __future__ import annotations

# API Router, Query, HTTP 예외 처리 기능 사용
from fastapi import (
    APIRouter,
    HTTPException,
    Query,
)

# 이미지 바이트 응답 생성 기능 사용
from fastapi.responses import Response

# Map 정보, 이미지, 좌표 변환 기능 사용
from ..services.map_service import (
    get_public_map_info,
    pgm_to_png_bytes,
    world_to_pixel,
)

# Route Graph 조회 및 변환 기능 사용
from ..services.route_graph import (
    build_renderable_geojson,
    get_node,
    graph_summary,
    list_nodes,
    load_route_graph,
)


# Map 및 Route Graph API Router 생성
router = APIRouter(
    prefix="/api",
    tags=["map-route"],
)


# ============================================================
# Map Info
# ============================================================

# Frontend 공개용 Map 정보 조회 API 생성
@router.get("/map/info")
async def get_map_info():

    try:

        # Map 메타데이터 및 World 영역 정보 반환
        return get_public_map_info()

    except Exception as exc:

        raise HTTPException(
            status_code=500,
            detail=str(exc),
        ) from exc


# ============================================================
# Map Image
# ============================================================

# Map 이미지 조회 API 생성
@router.get("/map/image")
async def get_map_image():

    try:

        # PGM Map 이미지를 PNG 응답으로 생성
        return Response(
            content=pgm_to_png_bytes(),
            media_type="image/png",
        )

    except Exception as exc:

        raise HTTPException(
            status_code=500,
            detail=str(exc),
        ) from exc


# ============================================================
# Route Graph
# ============================================================

# Route Graph GeoJSON 조회 API 생성
@router.get("/route/graph")
async def get_route_graph(
    raw: bool = Query(
        default=False
    ),
):

    """
    raw=False

        frontend가 바로 사용할 수 있게
        edge coordinates를 생성한 GeoJSON.

    raw=True

        원본 test.geojson 반환.
    """

    try:

        # raw 요청 시 원본 GeoJSON 사용
        if raw:

            return load_route_graph()

        # Frontend 렌더링용 GeoJSON 생성
        return build_renderable_geojson()

    except Exception as exc:

        raise HTTPException(
            status_code=500,
            detail=str(exc),
        ) from exc


# ============================================================
# Route Summary
# ============================================================

# Route Graph 요약 정보 조회 API 생성
@router.get("/route/summary")
async def get_route_summary():

    try:

        # Node 및 Edge 개수 요약 정보 반환
        return graph_summary()

    except Exception as exc:

        raise HTTPException(
            status_code=500,
            detail=str(exc),
        ) from exc


# ============================================================
# Route Nodes
# ============================================================

# 전체 Route Graph Node 조회 API 생성
@router.get("/route/nodes")
async def get_route_nodes(
    include_pixel: bool = Query(
        default=True
    ),
):

    try:

        # 전체 Node 목록 생성
        nodes = list_nodes()

        # 요청 시 World 좌표를 Pixel 좌표로 변환
        if include_pixel:

            for node in nodes:

                # Node World 좌표를 이미지 Pixel 좌표로 변환
                px, py = world_to_pixel(
                    node["x"],
                    node["y"],
                )

                node["pixel_x"] = px

                node["pixel_y"] = py

        return nodes

    except Exception as exc:

        raise HTTPException(
            status_code=500,
            detail=str(exc),
        ) from exc


# ============================================================
# 특정 Node
# ============================================================

@router.get(
    "/route/nodes/{node_id}"
)
# 특정 Route Graph Node 조회 기능
async def get_route_node(
    node_id: str,
):

    try:

        # Node ID 기준 Route Graph Node 조회
        node = get_node(
            node_id
        )

        px, py = world_to_pixel(
            node["x"],
            node["y"],
        )

        node["pixel_x"] = px

        node["pixel_y"] = py

        return node

    except KeyError as exc:

        raise HTTPException(
            status_code=404,
            detail=str(exc),
        ) from exc

    except Exception as exc:

        raise HTTPException(
            status_code=500,
            detail=str(exc),
        ) from exc