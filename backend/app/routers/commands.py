from __future__ import annotations

from uuid import uuid4

from fastapi import APIRouter, HTTPException
from fastapi.concurrency import run_in_threadpool

from ..schemas.command import GoalCoordinateRequest, GoalNodeRequest, LlmRoutePreviewRequest, StopRequest
from ..ros2.ros_gateway import ros_gateway
from ..services.mode_service import mode_manager
from ..services.scenario_service import scenario_manager
from ..services.command_service import navigate_to_node
from ..services.route_graph import load_route_graph
from ..services.fleet_manager import fleet_manager
from ..schemas.robot import normalize_robot_id
from ..models.robot import RobotState

router = APIRouter(prefix="/api/command", tags=["commands"])

# 추론 중 정지 또는 새 요청이 오면 이전 결과로 출발하지 않는다.
_llm_requests: dict[str, str] = {}


@router.get("/route-models")
async def route_models():
    """Return models explicitly enabled in the benchmark configuration."""
    from ..services.route_model_catalog import enabled_route_models
    try:
        return enabled_route_models()
    except (OSError, ValueError) as exc:
        raise HTTPException(status_code=503, detail=f"모델 목록을 읽지 못했습니다: {exc}") from exc


def _preview_start_node(robot_id: str, mode: str) -> str:
    """Read a stationary robot's occupied node without modifying navigation state."""
    if mode == "simulation":
        from ..services.mock_data import mock_fms
        robot = mock_fms.robot_snapshot(robot_id, mode)
        if robot.get("goal_node") is not None or robot.get("route") is not None:
            raise ValueError("로봇이 주행 중이거나 대기 중입니다. 정지 후 다시 시도하세요.")
        start = robot.get("occupied_node")
    else:
        resolved_id = normalize_robot_id(robot_id)
        robot = fleet_manager.get_robot(resolved_id)
        if robot is None or not robot.connected:
            raise ValueError(f"연결된 로봇을 찾을 수 없습니다: {robot_id}")
        with robot._lock:
            if robot.state != RobotState.IDLE or robot.route is not None or ros_gateway.navigation_active(resolved_id):
                raise ValueError("로봇이 주행 중이거나 대기 중입니다. 정지 후 다시 시도하세요.")
            start = robot.occupied_node
    if start is None:
        raise ValueError("현재 로봇이 노드 위에 있지 않아 경로를 계산할 수 없습니다.")
    return str(start)


@router.post("/llm-route-preview")
async def llm_route_preview(payload: LlmRoutePreviewRequest):
    """Calculate and validate a route; never dispatch a movement command."""
    try:
        scenario_manager.ensure_available(payload.robot_id)
        from ..services.llm_route_preview import preview_llm_route
        mode = mode_manager.mode
        start = _preview_start_node(payload.robot_id, mode)
        graph = load_route_graph()
        result = await run_in_threadpool(
            preview_llm_route, graph, start, payload.node_id,
            selector=payload.selector, model=payload.model,
        )
        if mode_manager.mode != mode:
            raise HTTPException(status_code=409, detail="모드가 변경되어 미리보기가 리셋되었습니다.")
        return {
            "mode": mode,
            "robot_id": payload.robot_id,
            "start_node": start,
            "target_node": str(payload.node_id),
            "dispatched": False,
            **result,
        }
    except HTTPException:
        raise
    except (KeyError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"LLM 경로 미리보기에 실패했습니다: {exc}") from exc


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
        robot_id = normalize_robot_id(payload.robot_id)
        _llm_requests.pop(robot_id, None)
        if payload.driving_mode == "standard":
            return navigate_to_node(payload.robot_id, payload.node_id, mode_manager.mode)
        token = uuid4().hex
        _llm_requests[robot_id] = token
        try:
            from ..services.llm_route_preview import preview_llm_route
            mode = mode_manager.mode
            start = _preview_start_node(payload.robot_id, mode)
            graph = load_route_graph()
            # 모델 호출은 잠금·이벤트 루프 밖에서 수행하고 완성 경로만 예약한다.
            preview = await run_in_threadpool(
                preview_llm_route, graph, start, payload.node_id,
                selector=payload.selector, model=payload.model,
            )
            if (_llm_requests.get(robot_id) != token or mode_manager.mode != mode
                    or load_route_graph() != graph):
                raise HTTPException(status_code=409, detail="정지·새 요청·모드 또는 맵 변경으로 LLM 결과를 취소했습니다.")
            scenario_manager.ensure_available(payload.robot_id)
            if _preview_start_node(payload.robot_id, mode) != start:
                raise ValueError("경로 생성 중 로봇의 출발 노드가 변경되었습니다.")
            result = navigate_to_node(payload.robot_id, payload.node_id, mode, required_path=preview["path"])
            return dict(result, driving_mode="llm", selector=payload.selector,
                        model=payload.model, llm_preview=preview)
        finally:
            if _llm_requests.get(robot_id) == token:
                _llm_requests.pop(robot_id, None)

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
        _llm_requests.pop(normalize_robot_id(payload.robot_id), None)
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
        _llm_requests.clear()
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
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
