from __future__ import annotations

from contextlib import asynccontextmanager
import logging
import os
from time import perf_counter
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from .config import CORS_ORIGINS
from .routers.commands import router as commands_router
from .routers.connections import router as connections_router
from .routers.map import router as map_router
from .routers.mode import router as mode_router
from .routers.robots import router as robots_router
from .routers.websocket import router as websocket_router
from .routers.client_logs import router as client_logs_router
from .routers.orders import router as orders_router
from .routers.omx import router as omx_router

from .logging_config import configure_logging
from .config import MQTT_ENABLED, SLOW_REQUEST_MS
from .services.map_service import load_map_metadata
from .services.mode_service import mode_manager
from .services.route_graph import load_route_graph

import threading

import rclpy
from rclpy.executors import ExternalShutdownException, SingleThreadedExecutor

from .ros2.fms_ros_node import FmsRosNode
from .ros2.ros_gateway import ros_gateway

import asyncio
from contextlib import suppress
from time import monotonic

from .services.mock_data import mock_fms
from .services.websocket_manager import manager
from .services.mqtt_manager import mqtt_manager
from .services.order_service import order_service

configure_logging()
logger = logging.getLogger("fms.main")


@asynccontextmanager
async def lifespan(app: FastAPI):

    logger.info(
        "event=backend_start mode=%s ros_domain_id=%s rmw=%s discovery_range=%s",
        mode_manager.mode,
        os.getenv("ROS_DOMAIN_ID", "unset"),
        os.getenv("RMW_IMPLEMENTATION", "unset"),
        os.getenv("ROS_AUTOMATIC_DISCOVERY_RANGE", "unset"),
    )

    load_map_metadata()
    load_route_graph()

    # ROS2 초기화
    rclpy.init()

    ros_node = FmsRosNode()

    executor = SingleThreadedExecutor()
    executor.add_node(ros_node)

    # RosGateway에 실제 ROS Node 연결
    ros_gateway.set_ros_node(ros_node)

    # OMX 결과를 주문의 다음 이동 단계와 연결한다.
    mqtt_manager.set_result_callback(order_service.handle_omx_result)
    mqtt_manager.set_progress_callback(order_service.handle_omx_progress)
    if MQTT_ENABLED:
        mqtt_manager.start()
    else:
        logger.info("event=mqtt_disabled")

    # FastAPI와 별도 Thread에서 ROS2 spin
    def spin_ros() -> None:
        try:
            executor.spin()
        except ExternalShutdownException:
            logger.info("event=ros_executor_shutdown")
        except Exception:
            logger.exception("event=ros_executor_stopped_unexpectedly")

    ros_thread = threading.Thread(
        target=spin_ros,
        daemon=True,
        name="fms-ros-executor",
    )

    ros_thread.start()

    simulation_task = asyncio.create_task(
        run_mock_simulation(),
        name="mock-simulation",
    )

    try:
        yield

    finally:
        logger.info("event=backend_shutdown_started")
        simulation_task.cancel()
        mqtt_manager.stop()

        try:
            with suppress(asyncio.CancelledError):
                await simulation_task
        finally:
            executor.shutdown()
            ros_node.destroy_node()

            if rclpy.ok():
                rclpy.shutdown()

            ros_thread.join(timeout=2.0)
            logger.info("event=backend_shutdown_complete")


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


@app.middleware("http")
async def request_logging(request: Request, call_next):
    request_id = request.headers.get("x-request-id") or uuid4().hex[:12]
    started = perf_counter()
    try:
        response = await call_next(request)
    except Exception:
        duration_ms = (perf_counter() - started) * 1000
        logger.exception(
            "event=http_request_failed request_id=%s method=%s path=%s duration_ms=%.1f",
            request_id,
            request.method,
            request.url.path,
            duration_ms,
        )
        raise

    duration_ms = (perf_counter() - started) * 1000
    response.headers["x-request-id"] = request_id
    if response.status_code >= 400:
        logger.warning(
            "event=http_error request_id=%s method=%s path=%s status=%s duration_ms=%.1f",
            request_id,
            request.method,
            request.url.path,
            response.status_code,
            duration_ms,
        )
    elif duration_ms >= SLOW_REQUEST_MS:
        logger.warning(
            "event=http_slow request_id=%s method=%s path=%s status=%s duration_ms=%.1f",
            request_id,
            request.method,
            request.url.path,
            response.status_code,
            duration_ms,
        )
    return response


app.include_router(map_router)
app.include_router(mode_router)
app.include_router(robots_router)
app.include_router(commands_router)
app.include_router(connections_router)
app.include_router(websocket_router)
app.include_router(client_logs_router)
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
        "mqtt": mqtt_manager.status(),
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

        mock_fms.advance_simulation(dt, now)

        # 갱신 후의 상태를 웹에 전송
        for state in mock_fms.robot_snapshots(mode):
            await manager.broadcast(
                {
                    "type": "telemetry",
                    "data": state,
                }
            )
