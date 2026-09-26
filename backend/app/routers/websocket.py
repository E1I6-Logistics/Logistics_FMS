from __future__ import annotations

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from ..ros2.ros_gateway import ros_gateway
from ..services.mock_data import mock_fms
from ..services.mode_service import mode_manager
from ..services.websocket_manager import manager

router = APIRouter(tags=["websocket"])


@router.websocket("/ws/dashboard")
async def dashboard_websocket(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        await websocket.send_json(
            {"type": "system", "data": {"mode": mode_manager.mode, "source": "mock"}}
        )
        for state in mock_fms.robot_snapshots(mode_manager.mode):
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
                await websocket.send_json({"type": "error", "message": str(exc)})
    except WebSocketDisconnect:
        pass
