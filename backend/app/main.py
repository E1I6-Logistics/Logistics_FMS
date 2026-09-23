from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .config import CORS_ORIGINS
from .routers.commands import router as commands_router
from .routers.connections import router as connections_router
from .routers.map import router as map_router
from .routers.mode import router as mode_router
from .routers.robots import router as robots_router
from .routers.websocket import router as websocket_router
from .services.map_service import load_map_metadata
from .services.mode_service import mode_manager
from .services.route_graph import load_route_graph


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Validate static frontend assets; no external control runtime is started."""
    load_map_metadata()
    load_route_graph()
    yield


app = FastAPI(
    title="E1I6 Logistics FMS API",
    version="3.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(map_router)
app.include_router(mode_router)
app.include_router(robots_router)
app.include_router(commands_router)
app.include_router(connections_router)
app.include_router(websocket_router)


@app.get("/")
async def root():
    return {
        "service": "E1I6 Logistics FMS API",
        "version": "3.0.0",
        "status": "ok",
        "architecture": "frontend contracts + in-memory mock",
        "docs": "/docs",
    }


@app.get("/health")
async def health():
    return {
        "status": "ok",
        "mode": mode_manager.mode,
        "data_source": "mock",
    }
