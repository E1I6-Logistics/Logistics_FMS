from __future__ import annotations

from fastapi import (
    APIRouter,
    WebSocket,
    WebSocketDisconnect,
)

from ..schemas.robot import (
    normalize_robot_id,
)

from ..services.ros_gateway import (
    ros_gateway,
)

from ..services.zenoh_service import (
    manager,
    status_snapshot,
)
from ..config import ROBOT_MODE
from ..services.simulation_gateway import simulation_gateway


router = APIRouter(
    tags=["websocket"]
)


# ============================================================
# Dashboard Telemetry
# ============================================================

@router.websocket(
    "/ws/dashboard"
)
async def dashboard_websocket(
    websocket: WebSocket,
):

    await manager.connect(
        websocket
    )

    # --------------------------------------------------------
    # 최초 시스템 상태
    # --------------------------------------------------------

    await websocket.send_json(
        {
            "type":
                "system",

            "data":
                {
                    "zenoh":
                        status_snapshot(),

                    "ros":
                        ros_gateway.status_snapshot(),
                },
        }
    )

    try:

        while True:

            # Frontend ping 등 수신.
            #
            # 실제 telemetry:
            #
            # Robot
            #   ↓
            # Native Zenoh
            #   ↓
            # zenoh_service
            #   ↓
            # manager.broadcast()
            #   ↓
            # Frontend

            await websocket.receive_text()

    except WebSocketDisconnect:

        manager.disconnect(
            websocket
        )

    except Exception:

        manager.disconnect(
            websocket
        )


# ============================================================
# cmd_vel
# ============================================================

@router.websocket(
    "/ws/cmd_vel"
)
async def cmd_vel_websocket(
    websocket: WebSocket,
):

    await websocket.accept()

    last_robot_id: (
        str | None
    ) = None

    try:

        while True:

            data = (
                await websocket
                .receive_json()
            )

            # ------------------------------------------------
            # Robot ID
            # ------------------------------------------------

            raw_robot_id = str(
                data.get(
                    "robot_id",
                    "",
                )
            ).strip()

            if not raw_robot_id:

                await websocket.send_json(
                    {
                        "type":
                            "error",

                        "message":
                            "robot_id required",
                    }
                )

                continue

            try:

                last_robot_id = (
                    normalize_robot_id(
                        raw_robot_id
                    )
                )

                # --------------------------------------------
                # FastAPI
                #   ↓
                # in-process Queue
                #   ↓
                # rclpy
                #   ↓
                # TwistStamped
                # --------------------------------------------

                linear_x = float(data.get("linear_x", 0.0))
                angular_z = float(data.get("angular_z", 0.0))
                if ROBOT_MODE == "simulation":
                    simulation_gateway.send_cmd_vel(last_robot_id, linear_x, angular_z)
                else:
                    ros_gateway.send_cmd_vel(last_robot_id, linear_x, angular_z)

            except ValueError as exc:

                await websocket.send_json(
                    {
                        "type":
                            "error",

                        "message":
                            str(exc),
                    }
                )

            except RuntimeError as exc:

                await websocket.send_json(
                    {
                        "type":
                            "error",

                        "message":
                            str(exc),
                    }
                )

    except WebSocketDisconnect:

        pass

    except Exception as exc:

        print(
            " -> [WARN] "
            "CMD_VEL WebSocket 오류: "
            f"{exc}"
        )

    finally:

        # ----------------------------------------------------
        # 안전 정지
        #
        # 브라우저 종료
        # Wi-Fi 단절
        # WebSocket 종료
        #
        # 마지막 제어 로봇에 0 속도 전송
        # ----------------------------------------------------

        if last_robot_id is not None:

            try:
                if ROBOT_MODE == "simulation":
                    simulation_gateway.stop_robot(last_robot_id)
                else:
                    ros_gateway.stop_robot(last_robot_id)

            except Exception:

                pass