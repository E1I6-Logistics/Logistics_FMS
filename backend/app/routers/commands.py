# 타입 힌트 지연 평가 기능 사용
from __future__ import annotations

# API Router 및 HTTP 예외 처리 기능 사용
from fastapi import APIRouter, HTTPException

# 명령 요청 데이터 Schema 사용
from ..schemas.command import GoalCoordinateRequest, GoalNodeRequest, StopRequest

# Route Graph Node 조회 기능 사용
from ..services.route_graph import get_node, list_nodes

# ROS2 명령 전송용 ROS Gateway 사용
from ..services.control_gateway import ros_gateway

from ..services.simulation_gateway import simulation_gateway
from ..services.mode_service import mode_manager

from ..services.zenoh_service import status_snapshot as zenoh_status_snapshot

from ..services.robot_manager import robot_manager
from ..services.route_planner import plan_route

import math

router = APIRouter(prefix="/api/command", tags=["commands"])


# ============================================================
# ROS Gateway 확인
# ============================================================


def _require_control() -> None:

    active = simulation_gateway.active if mode_manager.mode == "simulation" else ros_gateway.active
    if not active:

        raise HTTPException(
            status_code=503,
            detail="Robot control gateway inactive",
        )


def _route_waypoints_with_yaw(
    route: dict,
) -> list[tuple[float, float, float]]:
    points = route["waypoints"]
    result = []

    for index, (x, y) in enumerate(points):
        if index + 1 < len(points):
            next_x, next_y = points[index + 1]
            yaw = math.atan2(
                next_y - y,
                next_x - x,
            )
        elif result:
            yaw = result[-1][2]
        else:
            yaw = 0.0

        result.append((x, y, yaw))

    return result


def _nearest_route_node(
    x: float,
    y: float,
) -> dict:
    nodes = list_nodes()

    return min(
        nodes,
        key=lambda node: math.hypot(
            node["x"] - x,
            node["y"] - y,
        ),
    )


def _resolve_robot_start_node(
    robot_id: str,
) -> dict:
    state = robot_manager.snapshot(robot_id)

    if state is None:
        raise ValueError("로봇 상태가 없습니다.")

    if not state.get("map_pose_received"):
        raise ValueError("AMCL map 위치를 아직 받지 못했습니다.")

    node = _nearest_route_node(
        float(state["x"]),
        float(state["y"]),
    )

    distance = math.hypot(
        node["x"] - float(state["x"]),
        node["y"] - float(state["y"]),
    )

    if distance > 0.30:
        raise ValueError(f"로봇이 Route Graph에서 너무 멉니다: " f"{distance:.2f}m")

    return node


# ============================================================
# Command 상태
# ============================================================


# ROS Gateway 상태 조회 API 생성
@router.get("/status")
async def command_status():

    return {
        "ros": ros_gateway.status_snapshot(),
        "mode": mode_manager.mode,
        "simulation": simulation_gateway.status_snapshot(),
        "zenoh": zenoh_status_snapshot(),
    }


# ============================================================
# Backend Capability
# ============================================================


# Backend 지원 기능 조회 API 생성
@router.get("/capabilities")
async def command_capabilities():

    return {
        # ----------------------------------------------------
        # ROS Topic
        # ----------------------------------------------------
        "cmdVel": True,
        "stop": True,
        # ----------------------------------------------------
        # ROS Action
        # ----------------------------------------------------
        "coordinateGoal": True,
        "nodeMove": True,
        "navigateToPose": True,
        # ----------------------------------------------------
        # 추후 구현
        # ----------------------------------------------------
        "assign": False,
        "charge": False,
        "manualModeSwitch": False,
        # ----------------------------------------------------
        # Communication
        # ----------------------------------------------------
        "rosGateway": mode_manager.mode == "real",
        "simulationGateway": mode_manager.mode == "simulation",
        "nativeZenohTelemetry": True,
    }


# ============================================================
# 좌표 기반 Nav2 Goal
# ============================================================


# 좌표 기반 Nav2 이동 요청 API 생성
@router.post("/goal")
async def send_coordinate_goal(
    payload: GoalCoordinateRequest,
):

    _require_control()

    try:

        if mode_manager.mode == "simulation":
            result = simulation_gateway.navigate_to_pose(
                payload.robot_id, payload.target_x, payload.target_y, frame_id="map"
            )
        else:
            result = await ros_gateway.navigate_to_pose(
                payload.robot_id,
                payload.target_x,
                payload.target_y,
                frame_id="map",
            )
        result["mode"] = mode_manager.mode
        return result

    except ValueError as exc:

        raise HTTPException(
            status_code=400,
            detail=str(exc),
        ) from exc

    except RuntimeError as exc:

        raise HTTPException(
            status_code=503,
            detail=str(exc),
        ) from exc

    except Exception as exc:

        raise HTTPException(
            status_code=500,
            detail=str(exc),
        ) from exc


# ============================================================
# Node 기반 Nav2 Goal
# ============================================================


# Route Graph Node 기반 Nav2 이동 요청 API 생성
@router.post("/goal-node")
async def send_node_goal(
    payload: GoalNodeRequest,
):

    _require_control()

    try:

        # ----------------------------------------------------
        # GeoJSON Node 검색
        # ----------------------------------------------------

        # 요청한 Route Graph Node 정보 조회
        node = get_node(payload.node_id)

        # ----------------------------------------------------
        # Node 좌표 -> Nav2 NavigateToPose
        # ----------------------------------------------------

        if mode_manager.mode == "simulation":
            result = simulation_gateway.navigate_to_node(payload.robot_id, payload.node_id)
        else:
            start_node = _resolve_robot_start_node(payload.robot_id)

            route = plan_route(
                str(start_node["id"]),
                str(node["id"]),
            )

            waypoints = _route_waypoints_with_yaw(route)

            result = await ros_gateway.follow_waypoints(
                payload.robot_id,
                waypoints,
                frame_id="map",
            )

            result["route"] = {
                "node_ids": route["node_ids"],
                "edge_ids": route["edge_ids"],
            }

        # ----------------------------------------------------
        # Frontend 확인용 Node 정보
        # ----------------------------------------------------

        # Frontend 확인용 Node 정보 응답에 추가
        result["node"] = {
            "id": node["id"],
            "x": node["x"],
            "y": node["y"],
            "frame": node["frame"],
        }

        result["mode"] = mode_manager.mode

        return result

    except KeyError as exc:

        raise HTTPException(
            status_code=404,
            detail=str(exc),
        ) from exc

    except ValueError as exc:

        raise HTTPException(
            status_code=400,
            detail=str(exc),
        ) from exc

    except RuntimeError as exc:

        raise HTTPException(
            status_code=503,
            detail=str(exc),
        ) from exc

    except Exception as exc:

        raise HTTPException(
            status_code=500,
            detail=str(exc),
        ) from exc


# ============================================================
# Robot Stop
# ============================================================


# Robot 정지 요청 API 생성
@router.post("/stop")
async def stop_robot(
    payload: StopRequest,
):

    _require_control()

    try:

        if mode_manager.mode == "simulation":
            result = simulation_gateway.stop_robot(payload.robot_id)
        else:
            result = ros_gateway.stop_robot(payload.robot_id)
        result["mode"] = mode_manager.mode
        return result

    except ValueError as exc:

        raise HTTPException(
            status_code=400,
            detail=str(exc),
        ) from exc

    except RuntimeError as exc:

        raise HTTPException(
            status_code=503,
            detail=str(exc),
        ) from exc

    except Exception as exc:

        raise HTTPException(
            status_code=500,
            detail=str(exc),
        ) from exc
