from __future__ import annotations

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from time import strftime

from ..ros2.ros_gateway import ros_gateway
from ..services.mode_service import mode_manager
from ..services.scenario_service import scenario_manager
from ..services.websocket_manager import manager
from ..services.fleet_manager import fleet_manager
from ..services.map_service import world_to_pixel
from ..schemas.robot import to_ui_robot_id

router = APIRouter(tags=["websocket"])


@router.websocket("/ws/dashboard")
async def dashboard_websocket(websocket: WebSocket):
    await manager.connect(websocket)
    print(f"[{strftime('%Y-%m-%d %H:%M:%S')}] [INFO] [WS DASHBOARD] mode =", mode_manager.mode, flush=True)
    try:
        if mode_manager.mode == "simulation":
            from ..services.mock_data import mock_fms
            await websocket.send_json(
                {"type": "system", "data": {"mode": mode_manager.mode, "source": "mock"}}
            )
            for state in mock_fms.robot_snapshots(mode_manager.mode):
                await websocket.send_json({"type": "telemetry", "data": state})
        else:
            print(f"[{strftime('%Y-%m-%d %H:%M:%S')}] [INFO] [REAL WS] Sending telemetry for all robots", flush=True)
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
                    "pause_reason": robot.pause_reason,
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
                    "pose_source": "AMCL",
                }
                print(f"[{strftime('%Y-%m-%d %H:%M:%S')}] [INFO] [REAL WS]", robot.robot_id, "route=", robot.route, flush=True)
                await websocket.send_json({"type": "telemetry", "data": state})

        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        manager.disconnect(websocket)


@router.websocket("/ws/cmd_vel")
async def cmd_vel_websocket(websocket: WebSocket):
    await websocket.accept()
    try:
        while True:
            data = await websocket.receive_json()
            robot_id = str(data.get("robot_id", "")).strip()
            if not robot_id:
                await websocket.send_json({"type": "error", "message": "robot_id required"})
                continue
            try:
                linear = float(data.get("linear_x", 0.0))
                angular = float(data.get("angular_z", 0.0))
                if linear or angular:
                    scenario_manager.ensure_available(robot_id)
                if mode_manager.mode == "simulation":
                    from ..services.mock_data import mock_fms
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
                await websocket.send_json({"type": "error", "message": str(exc)})
    except WebSocketDisconnect:
        pass
