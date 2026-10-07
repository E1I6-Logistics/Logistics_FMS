from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .config import CORS_ORIGINS, REAL_NAVIGATION_INTERVAL_S
import logging

from .routers.commands import router as commands_router
from .routers.connections import router as connections_router
from .routers.map import router as map_router
from .routers.mode import router as mode_router
from .routers.robots import router as robots_router
from .routers.websocket import router as websocket_router
from .routers.orders import router as orders_router
from .routers.omx import router as omx_router

from .services.map_service import load_map_metadata
from .services.mode_service import mode_manager
from .services.route_graph import load_route_graph
import threading

import rclpy
from rclpy.executors import SingleThreadedExecutor

from .ros2.fms_ros_node import FmsRosNode
from .ros2.ros_gateway import ros_gateway

import asyncio
from contextlib import suppress
from time import monotonic, strftime

from .services.websocket_manager import manager
from .services.mqtt_manager import mqtt_manager

# Uvicorn의 INFO/ERROR 및 HTTP 접속 로그도 주행 로그와 같은 짧은 시각으로 표시한다.
for logger_name in ("uvicorn.error", "uvicorn.access"):
    for handler in logging.getLogger(logger_name).handlers:
        handler.setFormatter(logging.Formatter(
            "[%(asctime)s] %(levelname)s: %(message)s", datefmt="%H:%M:%S"))


@asynccontextmanager
async def lifespan(app: FastAPI):

    load_map_metadata()
    load_route_graph()
    mqtt_manager.start()

    # ROS2 초기화
    rclpy.init()

    ros_node = FmsRosNode()

    executor = SingleThreadedExecutor()
    executor.add_node(ros_node)

    # RosGateway에 실제 ROS Node 연결
    ros_gateway.set_ros_node(ros_node)

    # FastAPI와 별도 Thread에서 ROS2 spin
    ros_thread = threading.Thread(target=executor.spin, daemon=True)

    ros_thread.start()

    simulation_task = asyncio.create_task(
        run_mock_simulation(),
        name="mock-simulation",
    )

    navigation_task = asyncio.create_task(run_real_navigation(), name="real-navigation")

    try:
        yield

    finally:
        navigation_task.cancel()
        with suppress(asyncio.CancelledError):
            await navigation_task
        simulation_task.cancel()

        try:
            with suppress(asyncio.CancelledError):
                await simulation_task
        finally:
            executor.shutdown()
            ros_node.destroy_node()

            if rclpy.ok():
                rclpy.shutdown()

            ros_thread.join(timeout=2.0)

            # MQTT 종료
            mqtt_manager.stop()


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
app.include_router(orders_router)
app.include_router(omx_router)


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


async def run_mock_simulation() -> None:
    interval = 0.1  # 약 10Hz
    previous_time = monotonic()

    while True:
        await asyncio.sleep(interval)

        now = monotonic()
        dt = now - previous_time
        previous_time = now

        mode = mode_manager.mode
        if mode != "simulation":
            continue

        # 실제 모드 시작/실행에는 시뮬레이션 모듈이 필요하지 않다.
        from .services.mock_data import mock_fms
        mock_fms.advance_simulation(dt, now)

        # 갱신 후의 상태를 웹에 전송
        for state in mock_fms.robot_snapshots(mode):
            await manager.broadcast(
                {
                    "type": "telemetry",
                    "data": state,
                }
            )


async def run_real_navigation() -> None:
    # 화면 모드가 바뀌어도 이미 접수한 실제 ROS 요청의 관리를 계속한다.
    while True:
        await asyncio.sleep(REAL_NAVIGATION_INTERVAL_S)
        try:
            ros_gateway.advance_navigation()
        except (ValueError, RuntimeError):
            logging.getLogger(__name__).exception(
                "[%s] 실제 로봇 내비게이션 갱신 실패", strftime("%H:%M:%S"))
