# 타입 힌트 지연 평가 기능 사용
from __future__ import annotations

# FastAPI 비동기 처리와 ROS 결과 연결 기능 사용
import asyncio
# Quaternion 및 수치 계산 기능 사용
import math
# ROS 배포판 환경변수 조회 기능 사용
import os
# FastAPI 명령을 ROS Thread로 전달하기 위한 Queue 사용
import queue
# ROS Executor 별도 Thread 실행 기능 사용
import threading

from concurrent.futures import Future
from dataclasses import dataclass
from typing import Any

import rclpy

from action_msgs.msg import (
    GoalStatus,
)

from geometry_msgs.msg import (
    PoseWithCovarianceStamped,
    Twist,
    TwistStamped,
)

from nav2_msgs.action import (
    NavigateToPose,
)

from nav_msgs.msg import (
    Odometry,
)

from sensor_msgs.msg import (
    BatteryState,
)

from turtlebot3_msgs.msg import (
    SensorState,
)

from rclpy.action import (
    ActionClient,
)

from rclpy.executors import (
    MultiThreadedExecutor,
)

from rclpy.node import (
    Node,
)

from ..config import (
    CMD_VEL_MAX_ANGULAR,
    CMD_VEL_MAX_LINEAR,
    ROBOT_COUNT,
)

from ..schemas.robot import (
    normalize_robot_id,
    to_ui_robot_id,
)

from .robot_manager import (
    robot_manager,
)


# ============================================================
# 내부 Command
# ============================================================

# 내부 ROS 명령 데이터 객체 생성 기능 사용
@dataclass
# cmd_vel 전송용 내부 명령 구조
class _CmdVelCommand:

    robot_id: str
    linear_x: float
    angular_z: float


@dataclass
# NavigateToPose 전송용 내부 명령 구조
class _NavigateCommand:

    robot_id: str

    x: float
    y: float

    frame_id: str

    result_future: Future


# ============================================================
# Quaternion -> Yaw
# ============================================================

# Quaternion 자세 값을 Yaw 각도로 변환 기능
def _quaternion_to_yaw(
    x: float,
    y: float,
    z: float,
    w: float,
) -> float:

    siny_cosp = (
        2.0
        * (
            w * z
            + x * y
        )
    )

    cosy_cosp = (
        1.0
        - 2.0
        * (
            y * y
            + z * z
        )
    )

    return math.atan2(
        siny_cosp,
        cosy_cosp,
    )


# ============================================================
# Battery Status
# ============================================================

# BatteryState 상태 코드를 문자열 상태로 변환 기능
def _battery_status_name(
    value: int,
) -> str:

    status_map = {

        BatteryState.POWER_SUPPLY_STATUS_UNKNOWN:
            "UNKNOWN",

        BatteryState.POWER_SUPPLY_STATUS_CHARGING:
            "CHARGING",

        BatteryState.POWER_SUPPLY_STATUS_DISCHARGING:
            "DISCHARGING",

        BatteryState.POWER_SUPPLY_STATUS_NOT_CHARGING:
            "NOT_CHARGING",

        BatteryState.POWER_SUPPLY_STATUS_FULL:
            "FULL",
    }

    return status_map.get(
        value,
        "UNKNOWN",
    )


# ============================================================
# ROS Node
# ============================================================

# FMS용 ROS2 Node 생성 및 Robot별 ROS Interface 관리 기능
class FmsRosNode(Node):

    # ROS Node 및 Robot별 Interface 초기화
    def __init__(
        self,
    ) -> None:

        super().__init__("fms_ros_gateway")

        # ----------------------------------------------------
        # FastAPI -> ROS command Queue
        # ----------------------------------------------------

        # FastAPI 명령 전달용 내부 Queue 생성
        self._queue: queue.SimpleQueue[
            _CmdVelCommand
            | _NavigateCommand
        ] = queue.SimpleQueue()

        # ----------------------------------------------------
        # ROS Interface
        # ----------------------------------------------------

        # Robot별 cmd_vel Publisher 저장소 생성
        self._cmd_vel_publishers: dict[
            str,
            Any,
        ] = {}

        # Robot별 NavigateToPose Action Client 저장소 생성
        self._navigate_clients: dict[
            str,
            ActionClient,
        ] = {}

        # Robot별 Odom Subscriber 저장소 생성
        self._odom_subscribers: dict[
            str,
            Any,
        ] = {}

        # Robot별 AMCL Subscriber 저장소 생성
        self._amcl_subscribers: dict[
            str,
            Any,
        ] = {}

        # Robot별 BatteryState Subscriber 저장소 생성
        self._battery_subscribers: dict[
            str,
            Any,
        ] = {}

        # Robot별 TurtleBot3 SensorState Subscriber 저장소 생성
        self._sensor_state_subscribers: dict[
            str,
            Any,
        ] = {}

        # ----------------------------------------------------
        # ROS Distribution
        # ----------------------------------------------------

        # ROS_DISTRO 환경변수 기반 ROS 배포판 확인
        self._ros_distro = (
            os.getenv(
                "ROS_DISTRO",
                "",
            )
            .strip()
            .lower()
        )

        # TurtleBot3 공식 teleop 기준
        #
        # Humble = Twist
        # Jazzy  = TwistStamped
        # ROS 배포판에 따라 Twist 또는 TwistStamped 사용
        self._use_twist_stamped = (
            self._ros_distro
            != "humble"
        )

        # ----------------------------------------------------
        # Robot별 Interface
        # ----------------------------------------------------

        # 설정된 Robot 수만큼 ROS Interface 생성
        for index in range(
            1,
            ROBOT_COUNT + 1,
        ):

            robot_id = (
                f"robot{index}"
            )

            self._create_robot_interfaces(
                robot_id
            )

        # ----------------------------------------------------
        # Command Queue
        # ----------------------------------------------------

        # FastAPI 명령 Queue 주기 처리 Timer 생성
        self.create_timer(
            0.01,
            self._process_queue,
        )

        # ----------------------------------------------------
        # Connection timeout
        # ----------------------------------------------------

        self.create_timer(
            1.0,
            robot_manager.update_connection_states,
        )

        self.get_logger().info(
            "FMS ROS Gateway initialized "
            f"(ROS_DISTRO={self._ros_distro}, "
            f"robots={ROBOT_COUNT})"
        )

    # ========================================================
    # Robot ROS Interface
    # ========================================================

    # Robot별 Topic 및 Action Interface 생성 기능
    def _create_robot_interfaces(
        self,
        robot_id: str,
    ) -> None:

        # Robot cmd_vel Topic 이름 생성
        cmd_vel_topic = (
            f"/{robot_id}/cmd_vel"
        )

        # Robot odom Topic 이름 생성
        odom_topic = (
            f"/{robot_id}/odom"
        )

        # Robot AMCL pose Topic 이름 생성
        amcl_topic = (
            f"/{robot_id}/amcl_pose"
        )

        # Robot battery_state Topic 이름 생성
        battery_topic = (
            f"/{robot_id}/battery_state"
        )

        # Robot sensor_state Topic 이름 생성
        sensor_state_topic = (
            f"/{robot_id}/sensor_state"
        )

        # Robot NavigateToPose Action 이름 생성
        navigate_action = (
            f"/{robot_id}/navigate_to_pose"
        )

        # ----------------------------------------------------
        # cmd_vel Publisher
        # ----------------------------------------------------

        # ROS 배포판 기준 cmd_vel 메시지 타입 선택
        cmd_type = (
            TwistStamped
            if self._use_twist_stamped
            else Twist
        )

        # cmd_vel Publisher 생성
        self._cmd_vel_publishers[
            robot_id
        ] = self.create_publisher(
            cmd_type,
            cmd_vel_topic,
            10,
        )

        # ----------------------------------------------------
        # Nav2 NavigateToPose
        # ----------------------------------------------------

        # NavigateToPose Action Client 생성
        self._navigate_clients[
            robot_id
        ] = ActionClient(
            self,
            NavigateToPose,
            navigate_action,
        )

        # ----------------------------------------------------
        # Odom
        # ----------------------------------------------------

        # Odometry Subscriber 생성
        self._odom_subscribers[
            robot_id
        ] = self.create_subscription(
            Odometry,
            odom_topic,
            lambda msg, rid=robot_id:
                self._odom_callback(
                    rid,
                    msg,
                ),
            10,
        )

        # ----------------------------------------------------
        # AMCL
        # ----------------------------------------------------

        # AMCL Pose Subscriber 생성
        self._amcl_subscribers[
            robot_id
        ] = self.create_subscription(
            PoseWithCovarianceStamped,
            amcl_topic,
            lambda msg, rid=robot_id:
                self._amcl_callback(
                    rid,
                    msg,
                ),
            10,
        )

        # ----------------------------------------------------
        # Battery
        # ----------------------------------------------------

        # BatteryState Subscriber 생성
        self._battery_subscribers[
            robot_id
        ] = self.create_subscription(
            BatteryState,
            battery_topic,
            lambda msg, rid=robot_id:
                self._battery_callback(
                    rid,
                    msg,
                ),
            10,
        )

        # ----------------------------------------------------
        # TurtleBot3 SensorState
        # ----------------------------------------------------

        # TurtleBot3 SensorState Subscriber 생성
        self._sensor_state_subscribers[
            robot_id
        ] = self.create_subscription(
            SensorState,
            sensor_state_topic,
            lambda msg, rid=robot_id:
                self._sensor_state_callback(
                    rid,
                    msg,
                ),
            10,
        )

        self.get_logger().info(
            f"{robot_id} interfaces created"
        )

    # ========================================================
    # Odom Callback
    # ========================================================

    # Odom 수신 시 위치 및 속도 상태 갱신 기능
    def _odom_callback(
        self,
        robot_id: str,
        msg: Odometry,
    ) -> None:

        pose = (
            msg.pose.pose
        )

        twist = (
            msg.twist.twist
        )

        yaw = _quaternion_to_yaw(
            pose.orientation.x,
            pose.orientation.y,
            pose.orientation.z,
            pose.orientation.w,
        )

        robot_manager.update_odom(
            robot_id,

            pose.position.x,
            pose.position.y,
            yaw,

            twist.linear.x,
            twist.angular.z,
        )

    # ========================================================
    # AMCL Callback
    #
    # FMS에서 사용하는 map 기준 위치
    # ========================================================

    # AMCL 수신 시 Map 기준 위치 상태 갱신 기능
    def _amcl_callback(
        self,
        robot_id: str,
        msg: PoseWithCovarianceStamped,
    ) -> None:

        pose = (
            msg.pose.pose
        )

        yaw = _quaternion_to_yaw(
            pose.orientation.x,
            pose.orientation.y,
            pose.orientation.z,
            pose.orientation.w,
        )

        robot_manager.update_map_pose(
            robot_id,

            pose.position.x,
            pose.position.y,
            yaw,
        )

    # ========================================================
    # Battery Callback
    # ========================================================

    # BatteryState 수신 시 배터리 상태 갱신 기능
    def _battery_callback(
        self,
        robot_id: str,
        msg: BatteryState,
    ) -> None:

        percentage = None

        raw_percentage = (
            float(
                msg.percentage
            )
        )

        if (
            math.isfinite(
                raw_percentage
            )
            and raw_percentage >= 0.0
        ):

            # sensor_msgs/BatteryState 표준은
            # 0.0 ~ 1.0
            if raw_percentage <= 1.0:

                percentage = (
                    raw_percentage
                    * 100.0
                )

            else:

                percentage = (
                    raw_percentage
                )

        voltage = (
            float(msg.voltage)
            if math.isfinite(
                float(msg.voltage)
            )
            else None
        )

        current = (
            float(msg.current)
            if math.isfinite(
                float(msg.current)
            )
            else None
        )

        robot_manager.update_battery(
            robot_id,

            percentage,
            voltage,
            current,

            _battery_status_name(
                msg.power_supply_status
            ),
        )

    # ========================================================
    # TurtleBot3 SensorState Callback
    # ========================================================

    # TurtleBot3 SensorState 수신 시 센서 상태 갱신 기능
    def _sensor_state_callback(
        self,
        robot_id: str,
        msg: SensorState,
    ) -> None:

        robot_manager.update_sensor_state(
            robot_id,

            bumper=msg.bumper,

            cliff=msg.cliff,

            sonar=msg.sonar,

            illumination=
                msg.illumination,

            led=msg.led,

            button=msg.button,

            torque=msg.torque,

            left_encoder=
                msg.left_encoder,

            right_encoder=
                msg.right_encoder,

            battery=msg.battery,
        )

    # ========================================================
    # Queue Input
    # ========================================================

    # cmd_vel 명령을 ROS 처리 Queue에 추가 기능
    def enqueue_cmd_vel(
        self,
        robot_id: str,
        linear_x: float,
        angular_z: float,
    ) -> None:

        self._queue.put(
            _CmdVelCommand(
                robot_id=robot_id,
                linear_x=linear_x,
                angular_z=angular_z,
            )
        )

    # NavigateToPose 명령을 ROS 처리 Queue에 추가 기능
    def enqueue_navigate(
        self,
        robot_id: str,
        x: float,
        y: float,
        frame_id: str,
        result_future: Future,
    ) -> None:

        self._queue.put(
            _NavigateCommand(
                robot_id=robot_id,
                x=x,
                y=y,
                frame_id=frame_id,
                result_future=result_future,
            )
        )

    # ========================================================
    # Queue
    # ========================================================

    # 내부 Queue의 ROS 명령 분류 및 실행 기능
    def _process_queue(
        self,
    ) -> None:

        for _ in range(100):

            try:

                command = (
                    self._queue
                    .get_nowait()
                )

            except queue.Empty:

                break

            try:

                if isinstance(
                    command,
                    _CmdVelCommand,
                ):

                    self._publish_cmd_vel(
                        command
                    )

                elif isinstance(
                    command,
                    _NavigateCommand,
                ):

                    self._send_navigation_goal(
                        command
                    )

            except Exception as exc:

                self.get_logger().error(
                    f"ROS command error: "
                    f"{exc}"
                )

                if isinstance(
                    command,
                    _NavigateCommand,
                ):

                    if (
                        not command
                        .result_future
                        .done()
                    ):

                        command.result_future.set_exception(
                            exc
                        )

    # ========================================================
    # cmd_vel
    # ========================================================

    # Robot cmd_vel Topic 발행 기능
    def _publish_cmd_vel(
        self,
        command: _CmdVelCommand,
    ) -> None:

        publisher = (
            self._cmd_vel_publishers
            .get(
                command.robot_id
            )
        )

        if publisher is None:

            raise ValueError(
                "Unknown robot: "
                f"{command.robot_id}"
            )

        if self._use_twist_stamped:

            msg = (
                TwistStamped()
            )

            msg.header.stamp = (
                self.get_clock()
                .now()
                .to_msg()
            )

            msg.twist.linear.x = (
                float(
                    command.linear_x
                )
            )

            msg.twist.angular.z = (
                float(
                    command.angular_z
                )
            )

        else:

            msg = Twist()

            msg.linear.x = (
                float(
                    command.linear_x
                )
            )

            msg.angular.z = (
                float(
                    command.angular_z
                )
            )

        publisher.publish(
            msg
        )

    # ========================================================
    # NavigateToPose
    # ========================================================

    # Nav2 NavigateToPose Goal 전송 기능
    def _send_navigation_goal(
        self,
        command: _NavigateCommand,
    ) -> None:

        client = (
            self._navigate_clients
            .get(
                command.robot_id
            )
        )

        if client is None:

            raise ValueError(
                "Unknown robot: "
                f"{command.robot_id}"
            )

        if not client.server_is_ready():

            robot_manager.update_navigation(
                command.robot_id,

                navigation_state=
                    "UNAVAILABLE",

                status="ERROR",

                error_code=
                    "NAV_SERVER_UNAVAILABLE",

                error_message=
                    "NavigateToPose server unavailable",
            )

            if (
                not command
                .result_future
                .done()
            ):

                command.result_future.set_result(
                    {
                        "status":
                            "ACTION_SERVER_UNAVAILABLE",

                        "robot_id":
                            command.robot_id,

                        "ui_id":
                            to_ui_robot_id(
                                command.robot_id
                            ),
                    }
                )

            return

        goal = (
            NavigateToPose.Goal()
        )

        goal.pose.header.stamp = (
            self.get_clock()
            .now()
            .to_msg()
        )

        goal.pose.header.frame_id = (
            command.frame_id
        )

        goal.pose.pose.position.x = (
            float(command.x)
        )

        goal.pose.pose.position.y = (
            float(command.y)
        )

        goal.pose.pose.orientation.w = (
            1.0
        )

        robot_manager.update_navigation(
            command.robot_id,

            navigation_state=
                "GOAL_SENT",

            goal_reached=False,

            status="TASK_ASSIGNED",
        )

        send_future = (
            client.send_goal_async(
                goal,

                feedback_callback=(
                    lambda feedback:
                        self._navigation_feedback(
                            command.robot_id,
                            feedback,
                        )
                ),
            )
        )

        send_future.add_done_callback(
            lambda future:
                self._goal_response(
                    command,
                    future,
                )
        )

    # ========================================================
    # Goal Response
    # ========================================================

    # Nav2 Goal 승인 및 거절 결과 처리 기능
    def _goal_response(
        self,
        command: _NavigateCommand,
        future,
    ) -> None:

        try:

            goal_handle = (
                future.result()
            )

            if not goal_handle.accepted:

                robot_manager.update_navigation(
                    command.robot_id,

                    navigation_state=
                        "REJECTED",

                    status="ERROR",

                    error_code=
                        "NAV_GOAL_REJECTED",

                    error_message=
                        "Navigation goal rejected",
                )

                if (
                    not command
                    .result_future
                    .done()
                ):

                    command.result_future.set_result(
                        {
                            "status":
                                "REJECTED",

                            "robot_id":
                                command.robot_id,
                        }
                    )

                return

            robot_manager.update_navigation(
                command.robot_id,

                navigation_state=
                    "MOVING",

                goal_reached=False,

                status="MOVING",
            )

            if (
                not command
                .result_future
                .done()
            ):

                command.result_future.set_result(
                    {
                        "status":
                            "ACCEPTED",

                        "robot_id":
                            command.robot_id,

                        "ui_id":
                            to_ui_robot_id(
                                command.robot_id
                            ),

                        "action":
                            (
                                f"/{command.robot_id}"
                                "/navigate_to_pose"
                            ),

                        "target":
                            {
                                "x":
                                    command.x,

                                "y":
                                    command.y,

                                "frame":
                                    command.frame_id,
                            },
                    }
                )

            result_future = (
                goal_handle
                .get_result_async()
            )

            result_future.add_done_callback(
                lambda result:
                    self._navigation_result(
                        command.robot_id,
                        result,
                    )
            )

        except Exception as exc:

            robot_manager.update_navigation(
                command.robot_id,

                navigation_state=
                    "ERROR",

                status="ERROR",

                error_code=
                    "NAV_GOAL_ERROR",

                error_message=
                    str(exc),
            )

            if (
                not command
                .result_future
                .done()
            ):

                command.result_future.set_exception(
                    exc
                )

    # ========================================================
    # Feedback
    # ========================================================

    # Nav2 이동 중 남은 거리 Feedback 처리 기능
    def _navigation_feedback(
        self,
        robot_id: str,
        feedback_msg,
    ) -> None:

        try:

            feedback = (
                feedback_msg.feedback
            )

            distance_remaining = float(
                feedback.distance_remaining
            )

            robot_manager.update_navigation(
                robot_id,

                navigation_state=
                    "MOVING",

                goal_reached=False,

                distance_remaining=
                    distance_remaining,

                status="MOVING",
            )

        except Exception:

            pass

    # ========================================================
    # Result
    # ========================================================

    # Nav2 최종 주행 결과 처리 기능
    def _navigation_result(
        self,
        robot_id: str,
        future,
    ) -> None:

        try:

            wrapped_result = (
                future.result()
            )

            result_status = (
                wrapped_result.status
            )

            if (
                result_status
                == GoalStatus.STATUS_SUCCEEDED
            ):

                robot_manager.update_navigation(
                    robot_id,

                    navigation_state=
                        "SUCCEEDED",

                    goal_reached=True,

                    distance_remaining=
                        0.0,

                    status="COMPLETED",
                )

            elif (
                result_status
                == GoalStatus.STATUS_CANCELED
            ):

                robot_manager.update_navigation(
                    robot_id,

                    navigation_state=
                        "CANCELED",

                    goal_reached=False,

                    status="IDLE",
                )

            else:

                robot_manager.update_navigation(
                    robot_id,

                    navigation_state=
                        "FAILED",

                    goal_reached=False,

                    status="ERROR",

                    error_code=
                        "NAV_FAILED",

                    error_message=(
                        "NavigateToPose failed "
                        f"(status={result_status})"
                    ),
                )

        except Exception as exc:

            robot_manager.update_navigation(
                robot_id,

                navigation_state=
                    "ERROR",

                status="ERROR",

                error_code=
                    "NAV_RESULT_ERROR",

                error_message=
                    str(exc),
            )


# ============================================================
# ROS Gateway
# ============================================================

# FastAPI와 ROS2 Node 사이 실행 환경 관리 기능
class RosGateway:

    def __init__(
        self,
    ) -> None:

        self._node: (
            FmsRosNode
            | None
        ) = None

        self._executor: (
            MultiThreadedExecutor
            | None
        ) = None

        self._thread: (
            threading.Thread
            | None
        ) = None

        self._started = False

    # ========================================================
    # Start
    # ========================================================

    # ROS2 초기화 및 FmsRosNode 실행 기능
    def start(
        self,
    ) -> None:

        if self._started:

            return

        if not rclpy.ok():

            rclpy.init(
                args=None
            )

        self._node = (
            FmsRosNode()
        )

        self._executor = (
            MultiThreadedExecutor(
                num_threads=4
            )
        )

        self._executor.add_node(
            self._node
        )

        self._thread = (
            threading.Thread(
                target=self._spin,
                name="fms-ros-gateway",
                daemon=True,
            )
        )

        self._started = True

        self._thread.start()

        print(
            " -> ROS Gateway 활성화 완료"
        )

    # ========================================================
    # Spin
    # ========================================================

    # ROS Executor Spin 실행 기능
    def _spin(
        self,
    ) -> None:

        try:

            if (
                self._executor
                is not None
            ):

                self._executor.spin()

        except Exception as exc:

            if self._started:

                print(
                    " -> [ROS ERROR] "
                    f"Executor: {exc}"
                )

    # ========================================================
    # Stop
    # ========================================================

    # ROS Executor, Thread, Node 종료 및 자원 정리 기능
    def stop(
        self,
    ) -> None:

        if not self._started:

            return

        self._started = False

        try:

            if self._executor is not None:

                self._executor.shutdown(
                    timeout_sec=2.0
                )

        except Exception:

            pass

        try:

            if (
                self._thread is not None
                and self._thread.is_alive()
            ):

                self._thread.join(
                    timeout=2.0
                )

        except Exception:

            pass

        try:

            if (
                self._node is not None
                and self._executor
                is not None
            ):

                self._executor.remove_node(
                    self._node
                )

        except Exception:

            pass

        try:

            if self._node is not None:

                self._node.destroy_node()

        except Exception:

            pass

        self._node = None
        self._executor = None
        self._thread = None

        try:

            if rclpy.ok():

                rclpy.shutdown()

        except Exception:

            pass

        print(
            " -> ROS Gateway 종료"
        )

    # ========================================================
    # Active
    # ========================================================

    # ROS Gateway 활성 상태 조회 기능
    @property
    def active(
        self,
    ) -> bool:

        return (
            self._started
            and self._node
            is not None
        )

    # ========================================================
    # 상태
    # ========================================================

    # ROS Gateway 및 Robot 상태 요약 정보 생성 기능
    def status_snapshot(
        self,
    ) -> dict[str, Any]:

        return {

            "active":
                self.active,

            "node":
                (
                    "fms_ros_gateway"
                    if self.active
                    else None
                ),

            "robots":
                robot_manager.snapshots(),

            "interfaces": {
                "pose":
                    "amcl_pose",

                "odom":
                    "odom",

                "battery":
                    "battery_state",

                "sensor":
                    "sensor_state",

                "navigation":
                    "navigate_to_pose",
            },
        }

    # ========================================================
    # Robot State
    # ========================================================

    # 특정 Robot 상태 조회 기능
    def robot_state(
        self,
        robot_id: str,
    ) -> dict:

        return (
            robot_manager.snapshot(
                robot_id
            )
        )

    # 전체 Robot 상태 조회 기능
    def robot_states(
        self,
    ) -> list[dict]:

        return (
            robot_manager.snapshots()
        )

    # ========================================================
    # cmd_vel
    # ========================================================

    # 외부 요청 cmd_vel 검증 및 Queue 전달 기능
    def send_cmd_vel(
        self,
        robot_id: str,
        linear_x: float,
        angular_z: float,
    ) -> dict[str, Any]:

        if not self.active:

            raise RuntimeError(
                "ROS Gateway inactive"
            )

        backend_id = (
            normalize_robot_id(
                robot_id
            )
        )

        linear = max(
            -CMD_VEL_MAX_LINEAR,
            min(
                CMD_VEL_MAX_LINEAR,
                float(linear_x),
            ),
        )

        angular = max(
            -CMD_VEL_MAX_ANGULAR,
            min(
                CMD_VEL_MAX_ANGULAR,
                float(angular_z),
            ),
        )

        assert (
            self._node is not None
        )

        self._node.enqueue_cmd_vel(
            backend_id,
            linear,
            angular,
        )

        return {

            "status":
                "SUCCESS",

            "robot_id":
                backend_id,

            "ui_id":
                to_ui_robot_id(
                    backend_id
                ),

            "topic":
                f"/{backend_id}/cmd_vel",

            "linear_x":
                linear,

            "angular_z":
                angular,
        }

    # ========================================================
    # Stop
    # ========================================================

    # Robot 정지용 0 속도 cmd_vel 전송 기능
    def stop_robot(
        self,
        robot_id: str,
    ) -> dict[str, Any]:

        result = (
            self.send_cmd_vel(
                robot_id,
                0.0,
                0.0,
            )
        )

        result[
            "message"
        ] = (
            "정지 cmd_vel 전송 완료"
        )

        return result

    # ========================================================
    # NavigateToPose
    # ========================================================

    # 좌표 기반 NavigateToPose 명령 요청 및 응답 대기 기능
    async def navigate_to_pose(
        self,
        robot_id: str,
        x: float,
        y: float,
        frame_id: str = "map",
        timeout: float = 3.0,
    ) -> dict[str, Any]:

        if not self.active:

            raise RuntimeError(
                "ROS Gateway inactive"
            )

        backend_id = (
            normalize_robot_id(
                robot_id
            )
        )

        result_future: Future = (
            Future()
        )

        assert (
            self._node is not None
        )

        self._node.enqueue_navigate(
            backend_id,
            float(x),
            float(y),
            frame_id,
            result_future,
        )

        try:

            return (
                await asyncio.wait_for(
                    asyncio.wrap_future(
                        result_future
                    ),
                    timeout=timeout,
                )
            )

        except asyncio.TimeoutError:

            return {

                "status":
                    "TIMEOUT",

                "robot_id":
                    backend_id,

                "ui_id":
                    to_ui_robot_id(
                        backend_id
                    ),

                "action":
                    (
                        f"/{backend_id}"
                        "/navigate_to_pose"
                    ),

                "target": {
                    "x":
                        float(x),

                    "y":
                        float(y),

                    "frame":
                        frame_id,
                },
            }


# ============================================================
# Singleton
# ============================================================

# 전체 애플리케이션에서 공유할 RosGateway 객체 생성
ros_gateway = (
    RosGateway()
)