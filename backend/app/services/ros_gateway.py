from __future__ import annotations

import asyncio
import queue
import threading
from concurrent.futures import Future
from dataclasses import dataclass
from typing import Any

import rclpy

from geometry_msgs.msg import TwistStamped
from nav2_msgs.action import NavigateToPose

from rclpy.action import ActionClient
from rclpy.executors import MultiThreadedExecutor
from rclpy.node import Node

from ..config import (
    CMD_VEL_MAX_ANGULAR,
    CMD_VEL_MAX_LINEAR,
    ZENOH_ROBOT_COUNT,
)

from ..schemas.robot import (
    normalize_robot_id,
    to_ui_robot_id,
)


# ============================================================
# Internal Command
# ============================================================

@dataclass
class _CmdVelCommand:

    robot_id: str
    linear_x: float
    angular_z: float


@dataclass
class _NavigateCommand:

    robot_id: str
    x: float
    y: float
    frame_id: str
    result_future: Future


# ============================================================
# ROS Node
# ============================================================

class FmsRosNode(Node):

    def __init__(self) -> None:

        super().__init__(
            "fms_ros_gateway"
        )

        self._queue: queue.SimpleQueue[
            _CmdVelCommand | _NavigateCommand
        ] = queue.SimpleQueue()

        # ----------------------------------------------------
        # cmd_vel Publisher
        # ----------------------------------------------------

        self._cmd_vel_publishers: dict[
            str,
            Any,
        ] = {}

        # ----------------------------------------------------
        # Nav2 Action Client
        # ----------------------------------------------------

        self._navigate_clients: dict[
            str,
            ActionClient,
        ] = {}

        # ----------------------------------------------------
        # Robot별 ROS Interface 생성
        # ----------------------------------------------------

        for index in range(
            1,
            ZENOH_ROBOT_COUNT + 1,
        ):

            robot_id = (
                f"robot{index}"
            )

            cmd_vel_topic = (
                f"/{robot_id}/cmd_vel"
            )

            navigate_action = (
                f"/{robot_id}/navigate_to_pose"
            )

            self._cmd_vel_publishers[
                robot_id
            ] = self.create_publisher(
                TwistStamped,
                cmd_vel_topic,
                10,
            )

            self._navigate_clients[
                robot_id
            ] = ActionClient(
                self,
                NavigateToPose,
                navigate_action,
            )

        # ----------------------------------------------------
        # FastAPI -> ROS Queue 처리
        # ----------------------------------------------------

        self.create_timer(
            0.01,
            self._process_queue,
        )

        self.get_logger().info(
            "FMS ROS Gateway Node initialized"
        )

    # ========================================================
    # Queue Input
    # ========================================================

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
    # Queue 처리
    # ========================================================

    def _process_queue(self) -> None:

        # 한 timer cycle에서 과도하게 오래 점유하지 않도록 제한
        for _ in range(100):

            try:

                command = (
                    self._queue.get_nowait()
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
                    f"ROS command error: {exc}"
                )

                if isinstance(
                    command,
                    _NavigateCommand,
                ):

                    if not command.result_future.done():

                        command.result_future.set_exception(
                            exc
                        )

    # ========================================================
    # cmd_vel
    # ========================================================

    def _publish_cmd_vel(
        self,
        command: _CmdVelCommand,
    ) -> None:

        publisher = (
            self._cmd_vel_publishers.get(
                command.robot_id
            )
        )

        if publisher is None:

            raise ValueError(
                "Unknown robot: "
                f"{command.robot_id}"
            )

        msg = TwistStamped()

        msg.header.stamp = (
            self.get_clock()
            .now()
            .to_msg()
        )

        msg.header.frame_id = ""

        msg.twist.linear.x = float(
            command.linear_x
        )

        msg.twist.linear.y = 0.0
        msg.twist.linear.z = 0.0

        msg.twist.angular.x = 0.0
        msg.twist.angular.y = 0.0

        msg.twist.angular.z = float(
            command.angular_z
        )

        publisher.publish(
            msg
        )

    # ========================================================
    # NavigateToPose Action
    # ========================================================

    def _send_navigation_goal(
        self,
        command: _NavigateCommand,
    ) -> None:

        client = (
            self._navigate_clients.get(
                command.robot_id
            )
        )

        if client is None:

            raise ValueError(
                "Unknown robot: "
                f"{command.robot_id}"
            )

        # Nav2 Action Server 확인
        if not client.server_is_ready():

            if not command.result_future.done():

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

                        "action":
                            (
                                f"/{command.robot_id}"
                                "/navigate_to_pose"
                            ),

                        "target":
                            {
                                "x": command.x,
                                "y": command.y,
                                "frame":
                                    command.frame_id,
                            },
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

        goal.pose.pose.position.z = 0.0

        # 현재 API에는 yaw가 없으므로
        # 회전 없는 identity quaternion 사용
        goal.pose.pose.orientation.x = 0.0
        goal.pose.pose.orientation.y = 0.0
        goal.pose.pose.orientation.z = 0.0
        goal.pose.pose.orientation.w = 1.0

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
    # Action Goal Response
    # ========================================================

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

                if not command.result_future.done():

                    command.result_future.set_result(
                        {
                            "status":
                                "REJECTED",

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
                                    "x": command.x,
                                    "y": command.y,
                                    "frame":
                                        command.frame_id,
                                },
                        }
                    )

                return

            # Goal accepted
            if not command.result_future.done():

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
                                "x": command.x,
                                "y": command.y,
                                "frame":
                                    command.frame_id,
                            },
                    }
                )

            result_future = (
                goal_handle.get_result_async()
            )

            result_future.add_done_callback(
                lambda result:
                    self._navigation_result(
                        command.robot_id,
                        result,
                    )
            )

        except Exception as exc:

            if not command.result_future.done():

                command.result_future.set_exception(
                    exc
                )

    # ========================================================
    # Action Feedback
    # ========================================================

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

            self.get_logger().debug(
                f"{robot_id} navigation "
                f"distance_remaining="
                f"{distance_remaining:.3f}"
            )

        except Exception:

            pass

    # ========================================================
    # Action Result
    # ========================================================

    def _navigation_result(
        self,
        robot_id: str,
        future,
    ) -> None:

        try:

            wrapped_result = (
                future.result()
            )

            self.get_logger().info(
                f"{robot_id} navigation "
                f"finished status="
                f"{wrapped_result.status}"
            )

        except Exception as exc:

            self.get_logger().error(
                f"{robot_id} navigation "
                f"result error: {exc}"
            )


# ============================================================
# ROS Gateway
# ============================================================

class RosGateway:

    def __init__(self) -> None:

        self._node: (
            FmsRosNode | None
        ) = None

        self._executor: (
            MultiThreadedExecutor | None
        ) = None

        self._thread: (
            threading.Thread | None
        ) = None

        self._started = False

    # ========================================================
    # Start
    # ========================================================

    def start(self) -> None:

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
                num_threads=2
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
    # Executor
    # ========================================================

    def _spin(self) -> None:

        try:

            if self._executor is not None:

                self._executor.spin()

        except Exception as exc:

            # shutdown 과정에서 발생하는 executor 예외는
            # 정상 종료 중이면 출력하지 않음.
            if self._started:

                print(
                    " -> [ROS ERROR] "
                    f"Executor: {exc}"
                )

    # ========================================================
    # Stop
    # ========================================================

    def stop(self) -> None:

        if not self._started:

            return

        # 먼저 종료 상태로 변경
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
                and self._executor is not None
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
    # 상태
    # ========================================================

    @property
    def active(self) -> bool:

        return (
            self._started
            and self._node is not None
        )

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
                [
                    f"robot{i}"
                    for i in range(
                        1,
                        ZENOH_ROBOT_COUNT + 1,
                    )
                ],
        }

    # ========================================================
    # cmd_vel
    # ========================================================

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

        backend_id = normalize_robot_id(
            robot_id
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

        assert self._node is not None

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

    def stop_robot(
        self,
        robot_id: str,
    ) -> dict[str, Any]:

        result = self.send_cmd_vel(
            robot_id,
            0.0,
            0.0,
        )

        result["message"] = (
            "정지 cmd_vel 전송 완료"
        )

        return result

    # ========================================================
    # NavigateToPose
    # ========================================================

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

        backend_id = normalize_robot_id(
            robot_id
        )

        result_future: Future = (
            Future()
        )

        assert self._node is not None

        self._node.enqueue_navigate(
            backend_id,
            float(x),
            float(y),
            frame_id,
            result_future,
        )

        try:

            return await asyncio.wait_for(
                asyncio.wrap_future(
                    result_future
                ),
                timeout=timeout,
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

                "target":
                    {
                        "x": float(x),
                        "y": float(y),
                        "frame": frame_id,
                    },
            }


# ============================================================
# Singleton
# ============================================================

ros_gateway = RosGateway()