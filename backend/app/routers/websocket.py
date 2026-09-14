from __future__ import annotations

from fastapi import (
    APIRouter,
    WebSocket,
    WebSocketDisconnect,
)

from ..schemas.robot import (
    normalize_robot_id,
)

from ..services.zenoh_service import (
    manager,
    publish_cmd_vel,
    publish_stop,
    status_snapshot,
)


router = APIRouter(
    tags=["websocket"]
)


# ============================================================
# Dashboard telemetry
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

    # 연결 직후 Zenoh/FMS 상태 전달
    await websocket.send_json(
        {
            "type":
                "system",

            "data":
                status_snapshot(),
        }
    )

    try:

        while True:

            # 클라이언트에서 ping 등 수신.
            #
            # 실제 telemetry 전송은
            #
            # Zenoh callback
            #     ↓
            # manager.broadcast()
            #
            # 에서 처리함.
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

    last_robot_id: str | None = None

    try:

        while True:

            data = (
                await websocket
                .receive_json()
            )

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

                publish_cmd_vel(
                    last_robot_id,
                    float(
                        data.get(
                            "linear_x",
                            0.0,
                        )
                    ),
                    float(
                        data.get(
                            "angular_z",
                            0.0,
                        )
                    ),
                )

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

        # 브라우저 종료
        # 네트워크 단절
        # WebSocket 종료
        #
        # → 마지막 로봇 강제 정지

        if last_robot_id is not None:

            try:

                publish_stop(
                    last_robot_id
                )

            except Exception:

                pass