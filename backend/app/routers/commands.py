from __future__ import annotations

from fastapi import APIRouter, HTTPException

from ..schemas.command import GoalCoordinateRequest, GoalNodeRequest, StopRequest
from ..ros2.ros_gateway import ros_gateway
from ..services.mode_service import mode_manager
from ..services.scenario_service import scenario_manager
from ..services.command_service import navigate_to_node

router = APIRouter(prefix="/api/command", tags=["commands"])


@router.post("/goal")
async def send_coordinate_goal(payload: GoalCoordinateRequest):
    try:
        scenario_manager.ensure_available(payload.robot_id)
        if mode_manager.mode != "simulation":
            raise ValueError("좌표 직접 설정은 Simulation 모드 전용입니다. 실제 이동은 goal-node를 사용하세요.")
        from ..services.mock_data import mock_fms
        result = mock_fms.navigate_to_pose(payload.robot_id, payload.target_x, payload.target_y)
        result["mode"] = mode_manager.mode
        return result
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/goal-node")
async def send_node_goal(payload: GoalNodeRequest):
    try:
        scenario_manager.ensure_available(payload.robot_id)
        return navigate_to_node(payload.robot_id, payload.node_id, mode_manager.mode)

    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.post("/charging")
async def charging_station(payload: StopRequest):
    try:
        scenario_manager.ensure_available(payload.robot_id)
        if mode_manager.mode == "simulation":
            raise ValueError("충전 스테이션 이동은 현재 Real 모드에서만 지원합니다.")

        result = ros_gateway.navigate_to_charging_station(payload.robot_id)
        result["mode"] = mode_manager.mode
        return result

    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.post("/stop")
async def stop_robot(payload: StopRequest):
    try:
        scenario_manager.interrupt(payload.robot_id)
        if mode_manager.mode == "simulation":
            from ..services.mock_data import mock_fms
            result = mock_fms.stop_robot(payload.robot_id)
        else:
            result = ros_gateway.emergency_stop(payload.robot_id)

        result["mode"] = mode_manager.mode
        return result

    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.post("/stop-all")
async def stop_all_robots():
    try:
        scenario_manager.interrupt()
        if mode_manager.mode == "simulation":
            from ..services.mock_data import mock_fms
            for robot in mock_fms.robot_snapshots("simulation"):
                mock_fms.stop_robot(robot["robot_id"])
            result = {"success": True, "command": "stop-all"}
        else:
            result = ros_gateway.emergency_stop_all()
        result["mode"] = mode_manager.mode

        return result

    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.post("/emergency-release")
async def emergency_release(payload: StopRequest):
    try:
        scenario_manager.ensure_available(payload.robot_id)
        if mode_manager.mode == "simulation":
            raise ValueError("비상정지 해제는 현재 Real 모드에서만 지원합니다.")

        result = ros_gateway.emergency_release(payload.robot_id)
        result["mode"] = mode_manager.mode

        return result

    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.post("/emergency-release-all")
async def emergency_release_all():
    try:
        scenario_manager.ensure_available()
        if mode_manager.mode == "simulation":
            raise ValueError("전체 비상정지 해제는 현재 Real 모드에서만 지원합니다.")

        result = ros_gateway.emergency_release_all()
        result["mode"] = mode_manager.mode

        return result

    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.post("/return-nearest-node")
async def return_nearest_node(payload: StopRequest):
    try:
        scenario_manager.ensure_available(payload.robot_id)
        if mode_manager.mode == "simulation":
            raise ValueError("가장 가까운 노드 복귀는 현재 Real 모드에서만 지원합니다.")

        result = ros_gateway.return_to_nearest_node(payload.robot_id)
        result["mode"] = mode_manager.mode
        return result

    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
