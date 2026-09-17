# 타입 힌트 지연 평가 기능 사용
from __future__ import annotations

# WebSocket Router 및 연결 종료 예외 처리 기능 사용
from fastapi import (
    APIRouter,
    WebSocket,
    WebSocketDisconnect,
)

# Robot ID 표준 형식 변환 기능 사용
from ..schemas.robot import (
    normalize_robot_id,
)

# ROS2 명령 전송 및 상태 조회용 ROS Gateway 사용
from ..services.ros_gateway import (
    ros_gateway,
)

# WebSocket Router 생성
router = APIRouter(
    tags=["websocket"]
)


# ============================================================
# Dashboard Telemetry
# ============================================================

# Dashboard WebSocket Endpoint 생성
@router.websocket(
    "/ws/dashboard"
)
async def dashboard_websocket(
    websocket: WebSocket,
):

    # WebSocket 연결 수락
    await websocket.accept()

    # 최초 ROS Gateway 시스템 상태 전송
    await websocket.send_json(
        {
            "type":
                "system",

            "data":
                {
                    "ros":
                        ros_gateway
                        .status_snapshot(),
                },
        }
    )

    try:

        while True:

            # Dashboard WebSocket 연결 유지용 메시지 수신
            await websocket.receive_text()

    except WebSocketDisconnect:

        pass

    except Exception:

        pass

# ============================================================
# cmd_vel
# ============================================================

@router.websocket(
    "/ws/cmd_vel"
)
# 실시간 cmd_vel 제어용 WebSocket 기능
async def cmd_vel_websocket(
    websocket: WebSocket,
):

    await websocket.accept()

    # 마지막 제어 Robot ID 저장
    last_robot_id: (
        str | None
    ) = None

    try:

        while True:

            # Frontend에서 cmd_vel JSON 데이터 수신
            data = (
                await websocket
                .receive_json()
            )

            # ------------------------------------------------
            # Robot ID
            # ------------------------------------------------

            # 수신 데이터에서 Robot ID 추출
            raw_robot_id = str(
                data.get(
                    "robot_id",
                    "",
                )
            ).strip()

            # Robot ID 누락 시 오류 응답 처리
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

                # Robot ID를 backend 표준 형식으로 변환
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

                # ROS Gateway를 통해 cmd_vel 명령 전송
                ros_gateway.send_cmd_vel(
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

            # Robot ID 또는 입력값 오류 처리
            except ValueError as exc:

                await websocket.send_json(
                    {
                        "type":
                            "error",

                        "message":
                            str(exc),
                    }
                )

            # ROS Gateway 비활성 상태 오류 처리
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

    # WebSocket 종료 시 안전 정지 처리
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

        # 마지막 제어 Robot이 있는 경우 정지 명령 실행
        if last_robot_id is not None:

            try:

                # 연결 종료 시 마지막 Robot 정지 명령 전송
                ros_gateway.stop_robot(
                    last_robot_id
                )

            except Exception:

                pass