from __future__ import annotations

from fastapi import (
    APIRouter,
    HTTPException,
    Query,
)

from fastapi.responses import Response

from ..services.map_service import (
    get_public_map_info,
    pgm_to_png_bytes,
    world_to_pixel,
)

from ..services.route_graph import (
    build_renderable_geojson,
    get_node,
    graph_summary,
    list_nodes,
    load_route_graph,
)


router = APIRouter(
    prefix="/api",
    tags=["map-route"],
)


# ============================================================
# Map Info
# ============================================================

@router.get("/map/info")
async def get_map_info():

    try:

        return get_public_map_info()

    except Exception as exc:

        raise HTTPException(
            status_code=500,
            detail=str(exc),
        ) from exc


# ============================================================
# Map Image
# ============================================================

@router.get("/map/image")
async def get_map_image():

    try:

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

        if raw:

            return load_route_graph()

        return build_renderable_geojson()

    except Exception as exc:

        raise HTTPException(
            status_code=500,
            detail=str(exc),
        ) from exc


# ============================================================
# Route Summary
# ============================================================

@router.get("/route/summary")
async def get_route_summary():

    try:

        return graph_summary()

    except Exception as exc:

        raise HTTPException(
            status_code=500,
            detail=str(exc),
        ) from exc


# ============================================================
# Route Nodes
# ============================================================

@router.get("/route/nodes")
async def get_route_nodes(
    include_pixel: bool = Query(
        default=True
    ),
):

    try:

        nodes = list_nodes()

        if include_pixel:

            for node in nodes:

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
async def get_route_node(
    node_id: str,
):

    try:

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