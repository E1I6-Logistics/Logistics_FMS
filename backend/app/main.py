from __future__ import annotations

import asyncio

from contextlib import (
    asynccontextmanager,
)

from fastapi import FastAPI

from fastapi.middleware.cors import (
    CORSMiddleware,
)

from .config import (
    CORS_ORIGINS,
)

from .database.database import (
    close_db,
    init_db,
)

from .routers.commands import (
    router as commands_router,
)

from .routers.connections import (
    router as connections_router,
)

from .routers.map import (
    router as map_router,
)

from .routers.robots import (
    router as robots_router,
)

from .routers.websocket import (
    router as websocket_router,
)

from .services.map_service import (
    load_map_metadata,
)

from .services.route_graph import (
    graph_summary,
)

from .services.zenoh_service import (
    start_zenoh,
    stop_zenoh,
)


# ============================================================
# FastAPI Lifecycle
# ============================================================

@asynccontextmanager
async def lifespan(
    app: FastAPI,
):

    # --------------------------------------------------------
    # PostgreSQL
    # --------------------------------------------------------

    await init_db()

    # --------------------------------------------------------
    # Map 확인
    # --------------------------------------------------------

    try:

        info = load_map_metadata()

        print(
            " -> Map 로드 완료: "
            f"{info['image_name']} "
            f"({info['width']}x"
            f"{info['height']}, "
            f"resolution="
            f"{info['resolution']})"
        )

    except Exception as exc:

        print(
            " -> [WARN] "
            "Map 로드 실패: "
            f"{exc}"
        )

    # --------------------------------------------------------
    # Route Graph 확인
    # --------------------------------------------------------

    try:

        summary = graph_summary()

        print(
            " -> Route Graph 로드 완료: "
            f"nodes={summary['nodes']}, "
            f"edges={summary['edges']}, "
            "edges_without_coordinates="
            f"{summary['edges_without_coordinates']}"
        )

    except Exception as exc:

        print(
            " -> [WARN] "
            "Route Graph 로드 실패: "
            f"{exc}"
        )

    # --------------------------------------------------------
    # Zenoh
    # --------------------------------------------------------

    start_zenoh(
        asyncio.get_running_loop()
    )

    try:

        yield

    finally:

        stop_zenoh()

        await close_db()


# ============================================================
# FastAPI
# ============================================================

app = FastAPI(

    title=(
        "E1I6 Logistics FMS API"
    ),

    version="1.0.0",

    lifespan=lifespan,
)


# ============================================================
# CORS
# ============================================================

app.add_middleware(

    CORSMiddleware,

    allow_origins=
        CORS_ORIGINS,

    allow_credentials=
        False,

    allow_methods=[
        "*"
    ],

    allow_headers=[
        "*"
    ],
)


# ============================================================
# Routers
# ============================================================

app.include_router(
    map_router
)

app.include_router(
    robots_router
)

app.include_router(
    commands_router
)

app.include_router(
    connections_router
)

app.include_router(
    websocket_router
)


# ============================================================
# Root
# ============================================================

@app.get("/")
async def root():

    return {

        "service":
            "E1I6 Logistics FMS API",

        "status":
            "ok",

        "docs":
            "/docs",
    }


# ============================================================
# Health Check
# ============================================================

@app.get("/health")
async def health():

    return {
        "status": "ok"
    }