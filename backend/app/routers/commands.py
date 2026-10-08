from __future__ import annotations

from fastapi import APIRouter, HTTPException
from fastapi.concurrency import run_in_threadpool

from ..schemas.command import GoalCoordinateRequest, GoalNodeRequest, LlmRoutePreviewRequest, StopRequest
from ..ros2.ros_gateway import ros_gateway
from ..services.mode_service import mode_manager
from ..services.route_graph import load_route_graph
from ..services.fleet_manager import fleet_manager
from ..schemas.robot import normalize_robot_id

router = APIRouter(prefix="/api/command", tags=["commands"])


@router.get("/route-models")
async def route_models():
    """Return only models enabled for route driving."""
    from ..services.route_model_catalog import enabled_route_models
    return enabled_route_models()


@router.post("/goal")
async def send_coordinate_goal(payload: GoalCoordinateRequest):
    try:
        if mode_manager.mode != "simulation":
            raise ValueError("좌표 직접 설정은 Simulation 모드 전용입니다. 실제 이동은 goal-node를 사용하세요.")
        from ..services.mock_data import mock_fms
        result = mock_fms.navigate_to_pose(payload.robot_id, payload.target_x, payload.target_y)
        result["mode"] = mode_manager.mode
        return result
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def _llm_start_node(robot_id: str, mode: str) -> str:
    """Read the robot's occupied node; never infer a route from a stale edge."""
    if mode == "simulation":
        from ..services.mock_data import mock_fms
        robot = mock_fms.robot_snapshot(robot_id, mode)
        if robot.get("goal_node") is not None or robot.get("route") is not None:
            raise ValueError("로봇이 주행 중이거나 대기 중입니다. 정지 후 다시 시도하세요.")
        start = robot.get("occupied_node")
    else:
        robot = fleet_manager.get_robot(normalize_robot_id(robot_id))
        if robot is None or not robot.connected:
            raise ValueError("실제 로봇이 연결되어 있지 않습니다.")
        if robot.goal_node is not None or robot.route is not None:
            raise ValueError("로봇이 주행 중이거나 대기 중입니다. 정지 후 다시 시도하세요.")
        start = robot.occupied_node
    if start is None:
        raise ValueError("현재 로봇이 노드 위에 있지 않아 경로를 계산할 수 없습니다.")
    return str(start)


def _other_occupied_nodes(robot_id: str, mode: str) -> set[str]:
    """Snapshot nodes physically occupied by other robots before model inference."""
    selected = normalize_robot_id(robot_id)
    if mode == "simulation":
        from ..services.mock_data import mock_fms
        return {
            str(robot["occupied_node"])
            for robot in mock_fms.robot_snapshots(mode)
            if normalize_robot_id(robot["robot_id"]) != selected
            and robot.get("occupied_node") is not None
        }
    occupied: set[str] = set()
    for robot in fleet_manager.get_all_robots():
        if normalize_robot_id(robot.robot_id) == selected:
            continue
        with robot._lock:
            if robot.occupied_node is not None:
                occupied.add(str(robot.occupied_node))
    return occupied


@router.post("/goal-node")
async def send_node_goal(payload: GoalNodeRequest):
    try:
        mode = mode_manager.mode
        required_path = None
        llm_result = None
        if payload.driving_mode == "llm":
            if payload.selector is None or payload.model is None:
                raise ValueError("경로 선택기와 모델을 선택하세요.")
            from ..services.llm_route_preview import preview_llm_route
            start = _llm_start_node(payload.robot_id, mode)
            graph = load_route_graph()
            llm_result = await run_in_threadpool(
                preview_llm_route, graph, start, payload.node_id,
                selector=payload.selector, model=payload.model,
                occupied_nodes=_other_occupied_nodes(payload.robot_id, mode),
            )
            # 최단거리 일치 여부는 비교 지표다. 유효한 유향 경로라면
            # 비최단 경로도 기존 예약·양보 제어에 전달한다.
            required_path = llm_result["path"]
            if mode_manager.mode != mode:
                raise HTTPException(status_code=409, detail="모드가 변경되어 주행하지 않았습니다.")
            if len(required_path) == 1:
                return {"success": True, "status": "ALREADY_ARRIVED",
                        "mode": mode, "driving_mode": "llm",
                        "llm": {**llm_result, "dispatched": False}}
        if mode == "simulation":
            from ..services.mock_data import mock_fms
            result = mock_fms.navigate_to_node(
                payload.robot_id, payload.node_id, required_path=required_path
            )
        else:
            result = ros_gateway.navigate_to_node(
                payload.robot_id, payload.node_id, required_path=required_path
            )
        result["mode"] = mode
        result["driving_mode"] = payload.driving_mode
        if llm_result is not None:
            result["llm"] = {**llm_result, "dispatched": True}
        return result

    except HTTPException:
        raise
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"LLM 주행 요청 실패: {exc}") from exc


@router.post("/llm-route-preview")
async def llm_route_preview(payload: LlmRoutePreviewRequest):
    """Calculate and validate without dispatching any robot command."""
    try:
        from ..services.llm_route_preview import preview_llm_route
        mode = mode_manager.mode
        start = _llm_start_node(payload.robot_id, mode)
        result = await run_in_threadpool(
            preview_llm_route, load_route_graph(), start, payload.node_id,
            selector=payload.selector, model=payload.model,
            occupied_nodes=_other_occupied_nodes(payload.robot_id, mode),
        )
        return {"mode": mode, "robot_id": payload.robot_id,
                "start_node": start, "target_node": str(payload.node_id),
                "dispatched": False, **result}
    except (KeyError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"LLM 경로 미리보기에 실패했습니다: {exc}") from exc


@router.post("/charging")
async def charging_station(payload: StopRequest):
    try:
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
        if mode_manager.mode == "simulation":
            raise ValueError("전체 비상정지는 현재 Real 모드에서만 지원합니다.")

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
        if mode_manager.mode == "simulation":
            raise ValueError("가장 가까운 노드 복귀는 현재 Real 모드에서만 지원합니다.")

        result = ros_gateway.return_to_nearest_node(payload.robot_id)
        result["mode"] = mode_manager.mode
        return result

    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
