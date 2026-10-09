from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from time import strftime

from ..models.robot import RobotState
from ..ros2.ros_gateway import ros_gateway
from ..services.fleet_manager import fleet_manager
from ..services.mode_service import mode_manager
from ..services.websocket_manager import manager
from .robots import fetch_robots
from ..schemas.robot import to_ui_robot_id

router = APIRouter(prefix="/api/mode", tags=["mode"])


class ModeRequest(BaseModel):
    mode: Literal["real", "simulation"]


def _snapshot() -> dict[str, object]:
    return {
        "mode": mode_manager.mode,
        "real_available": True,
        "simulation_active": mode_manager.mode == "simulation",
        "using_mock": mode_manager.mode == "simulation",
    }


@router.get("")
async def get_mode():
    return _snapshot()


@router.put("")
async def set_mode(payload: ModeRequest):
    from ..services.scenario_service import scenario_manager
    try:
        scenario_manager.ensure_available()
    except ValueError as exc:
        raise HTTPException(409, detail=str(exc)) from exc
    if mode_manager.mode == "real" and payload.mode == "simulation":
        # 표시 모드만 바뀌어도 실제 Goal은 계속 실행되므로 작업 중에는 전환하지 않는다.
        with ros_gateway._navigation.lock:
            navigation = ros_gateway._navigation
            busy = [robot.robot_id for robot in fleet_manager.get_all_robots()
                    if robot.state in (RobotState.MOVING, RobotState.WAITING,
                                       RobotState.TASK_ASSIGNED, RobotState.DOCKING)
                    or robot.order_id is not None
                    or robot.route is not None
                    or robot.navigation_type is not None
                    or robot.robot_id in navigation._requests
                    or robot.robot_id in navigation._executing
                    or robot.robot_id in navigation._stopping
                    or robot.robot_id in navigation._arrivals
                    or robot.robot_id in ros_gateway._waiting_omx
                    or (ros_gateway._ros_node is not None
                        and ros_gateway._ros_node.has_active_auxiliary(robot.robot_id))]
            if busy:
                print(f"[{strftime('%Y-%m-%d %H:%M:%S')}] [WARN] [MODE] real->simulation rejected: "
                      f"active_robots={busy}", flush=True)
                raise HTTPException(status_code=409, detail=f"실제 로봇 작업 중에는 모드를 변경할 수 없습니다: {busy}")
            mode_manager.set_mode(payload.mode)
    else:
        mode_manager.set_mode(payload.mode)
    # 실제 모드 전환에서는 시뮬레이션 모듈을 로드하지 않는다.
    if payload.mode == "simulation":
        from ..services.mock_data import mock_fms
        states = mock_fms.robot_snapshots(payload.mode)
    else:
        states = None
    if states is None:
        states = await fetch_robots()
        for state in states:
            state["ui_id"] = to_ui_robot_id(state["robot_id"])
    await manager.broadcast(
        {"type": "system", "data": {
            "mode": mode_manager.mode,
            "source": "mock" if mode_manager.mode == "simulation" else "ros2",
        }}
    )
    for state in states:
        await manager.broadcast({"type": "telemetry", "data": state})
    return _snapshot()
