# 타입 힌트 지연 평가 기능 사용
from __future__ import annotations

# FastAPI 시작/종료 Lifecycle 관리 기능 사용
from contextlib import (
    asynccontextmanager,
)

# FastAPI 애플리케이션 생성 기능 사용
from fastapi import FastAPI

# CORS 처리 기능 사용
from fastapi.middleware.cors import (
    CORSMiddleware,
)

# CORS 설정값 사용
from .config import (
    CORS_ORIGINS,
)

# Database 초기화 및 종료 기능 사용
from .database.database import (
    close_db,
    init_db,
)

# Command API Router 사용
from .routers.commands import (
    router as commands_router,
)

# Connection API Router 사용
from .routers.connections import (
    router as connections_router,
)

# Map API Router 사용
from .routers.map import (
    router as map_router,
)

# Robot API Router 사용
from .routers.robots import (
    router as robots_router,
)

# WebSocket Router 사용
from .routers.websocket import (
    router as websocket_router,
)

# Map 메타데이터 로드 기능 사용
from .services.map_service import (
    load_map_metadata,
)

# Route Graph 요약 정보 생성 기능 사용
from .services.route_graph import (
    graph_summary,
)

# ROS2 통신용 ROS Gateway 사용
from .services.ros_gateway import (
    ros_gateway,
)


# ============================================================
# FastAPI Lifecycle
# ============================================================

# FastAPI 시작 및 종료 Lifecycle 관리 기능
# yield 이전 Startup 처리, yield 이후 Shutdown 처리
@asynccontextmanager
async def lifespan(
    app: FastAPI,
):

    # --------------------------------------------------------
    # PostgreSQL
    # --------------------------------------------------------

# PostgreSQL 초기화 실행
    await init_db()

    print(
        " -> Database 초기화 완료"
    )

    # --------------------------------------------------------
    # Map
    # --------------------------------------------------------

    try:
# Map 메타데이터 로드 및 상태 확인

        info = (
            load_map_metadata()
        )

        print(
            " -> Map 로드 완료: "
            f"{info['image_name']} "
            f"({info['width']}x"
            f"{info['height']}, "
            f"resolution="
            f"{info['resolution']})"
        )

# Map 로드 실패 예외 처리
    except Exception as exc:

        print(
            " -> [WARN] "
            "Map 로드 실패: "
            f"{exc}"
        )

    # --------------------------------------------------------
    # Route Graph
    # --------------------------------------------------------

    try:
# Route Graph 요약 정보 생성 및 상태 확인

        summary = (
            graph_summary()
        )

        print(
            " -> Route Graph 로드 완료: "
            f"nodes={summary['nodes']}, "
            f"edges={summary['edges']}"
        )

# Route Graph 로드 실패 예외 처리
    except Exception as exc:

        print(
            " -> [WARN] "
            "Route Graph 로드 실패: "
            f"{exc}"
        )

    # --------------------------------------------------------
    # ROS Gateway
    # --------------------------------------------------------

    try:
# ROS Gateway 시작 및 ROS2 통신 기능 활성화

        ros_gateway.start()

# ROS Gateway 시작 실패 예외 처리
    except Exception as exc:

        print(
            " -> [WARN] "
            "ROS Gateway 시작 실패: "
            f"{exc}"
        )

    # --------------------------------------------------------
    # FastAPI
    # --------------------------------------------------------

    try:

# FastAPI 실제 실행 구간 시작
        yield

# 서버 종료 시 자원 정리 기능
    finally:

        try:
# ROS Gateway 종료 및 ROS2 자원 정리

            ros_gateway.stop()

        except Exception as exc:

            print(
                " -> [WARN] "
                "ROS Gateway 종료 오류: "
                f"{exc}"
            )

        try:
# PostgreSQL 연결 종료

            await close_db()

        except Exception as exc:

            print(
                " -> [WARN] "
                "Database 종료 오류: "
                f"{exc}"
            )

        print(
            " -> FMS Backend 종료 완료"
        )


# ============================================================
# FastAPI
# ============================================================

# FastAPI 애플리케이션 생성 및 Lifecycle 연결
app = FastAPI(

    title=(
        "E1I6 Logistics FMS API"
    ),

    version="3.0.0",

    lifespan=lifespan,
)


# ============================================================
# CORS
# ============================================================

# CORS Middleware 등록
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

# Map Router 등록
app.include_router(
    map_router
)

# Robot Router 등록
app.include_router(
    robots_router
)

# Command Router 등록
app.include_router(
    commands_router
)

# Connection Router 등록
app.include_router(
    connections_router
)

# WebSocket Router 등록
app.include_router(
    websocket_router
)


# ============================================================
# Root
# ============================================================

# Root API 생성
@app.get("/")
async def root():

    return {

        "service":
            "E1I6 Logistics FMS API",

        "version":
            "3.0.0",

        "status":
            "ok",

        "architecture":
            "ROS2 Gateway + "
            "zenoh-bridge-ros2dds",

        "docs":
            "/docs",
    }


# ============================================================
# Health
# ============================================================

# Backend 및 ROS Gateway 상태 확인 API 생성
@app.get("/health")
async def health():

    return {

        "status":
            "ok",

        "ros_gateway":
            ros_gateway
            .status_snapshot(),
    }