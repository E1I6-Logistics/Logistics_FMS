from __future__ import annotations

import logging
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from ..ros2.ros_gateway import ros_gateway
from ..services.mock_data import mock_fms
from ..services.mode_service import mode_manager
from ..services.websocket_manager import manager
from ..services.fleet_manager import fleet_manager
from ..services.map_service import world_to_pixel
from ..schemas.robot import to_ui_robot_id

router = APIRouter(tags=["websocket"])
logger = logging.getLogger("fms.websocket")


@router.websocket("/ws/dashboard")
async def dashboard_websocket(websocket: WebSocket):
    await manager.connect(websocket)
    print("[WS DASHBOARD] mode =", mode_manager.mode)
    try:
        if mode_manager.mode == "simulation":
            await websocket.send_json(
                {"type": "system", "data": {"mode": mode_manager.mode, "source": "mock"}}
            )
            for state in mock_fms.robot_snapshots(mode_manager.mode):
                await websocket.send_json({"type": "telemetry", "data": state})
        else:
            print("[REAL WS] Sending telemetry for all robots")
            await websocket.send_json(
                {"type": "system", "data": {"mode": mode_manager.mode, "source": "ros2"}}
            )
            for robot in fleet_manager.get_all_robots():
                pixel_x = None
                pixel_y = None

                if robot.x is not None and robot.y is not None:
                    pixel_x, pixel_y = world_to_pixel(robot.x, robot.y)

                state = {
                    "robot_id": robot.robot_id,
                    "ui_id": to_ui_robot_id(robot.robot_id),
                    "status": robot.state.value,
                    "battery": robot.battery,
                    "x": robot.x,
                    "y": robot.y,
                    "yaw": robot.yaw,
                    "current_node": robot.current_node,
                    "route": robot.route,
                    "connected": robot.connected,
                    "pixel_x": pixel_x,
                    "pixel_y": pixel_y,
                    "map_pose_received": robot.x is not None and robot.y is not None,
                    "mode": mode_manager.mode,
                    "source": "ros2",
                    "pose_source": "logitle_pose",
                    "order_items": robot.order_items.copy(),
                    "order_id": robot.order_id,
                    "order_status": robot.order_status,
                    "order_phase": robot.order_phase,
                    "loaded_count": robot.loaded_count,
                }
                print("[REAL WS]", robot.robot_id, "route=", robot.route)
                await websocket.send_json({"type": "telemetry", "data": state})

        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    except Exception:
        logger.exception(
            "event=dashboard_ws_unexpected_error connection_id=%s", id(websocket)
        )
    finally:
        manager.disconnect(websocket)


@router.websocket("/ws/cmd_vel")
async def cmd_vel_websocket(websocket: WebSocket):
    await websocket.accept()
    logger.info("event=cmd_vel_ws_connected connection_id=%s", id(websocket))
    try:
        while True:
            data = await websocket.receive_json()
            robot_id = str(data.get("robot_id", "")).strip()
            if not robot_id:
                await websocket.send_json({"type": "error", "message": "robot_id required"})
                continue
            try:
                if mode_manager.mode == "simulation":
                    acknowledgement = mock_fms.cmd_vel(
                        robot_id,
                        float(data.get("linear_x", 0.0)),
                        float(data.get("angular_z", 0.0)),
                    )
                else:
                    acknowledgement = ros_gateway.cmd_vel(
                        robot_id,
                        float(data.get("linear_x", 0.0)),
                        float(data.get("angular_z", 0.0)),
                    )

                await websocket.send_json(acknowledgement)

            except (TypeError, ValueError, RuntimeError) as exc:
                logger.warning(
                    "event=cmd_vel_rejected connection_id=%s robot_id=%s error=%s",
                    id(websocket),
                    robot_id or "unknown",
                    exc,
                )
                await websocket.send_json({"type": "error", "message": str(exc)})
    except WebSocketDisconnect:
        pass
    except Exception:
        logger.exception(
            "event=cmd_vel_ws_unexpected_error connection_id=%s", id(websocket)
        )
    finally:
        logger.info("event=cmd_vel_ws_disconnected connection_id=%s", id(websocket))
