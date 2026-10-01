from __future__ import annotations

import rclpy as rp
from rclpy.node import Node
import logging
import math
from threading import RLock

from rclpy.publisher import Publisher
from rclpy.subscription import Subscription
from rclpy.action import ActionClient

from geometry_msgs.msg import Quaternion
from geometry_msgs.msg import TwistStamped
from geometry_msgs.msg import PoseStamped
from geometry_msgs.msg import PoseWithCovarianceStamped
from nav2_msgs.action import FollowWaypoints

from ..services.fleet_manager import fleet_manager

from action_msgs.msg import GoalStatus
from sensor_msgs.msg import BatteryState
from turtlebot3_my_msg.action import PrecisionDock

try:
    from logitle_aruco_msgs.action import AlignAndCorrectWithAruco
except ImportError:
    AlignAndCorrectWithAruco = None


logger = logging.getLogger("fms.ros")


class FmsRosNode(Node):
    def __init__(self):
        super().__init__("fms_node")
        self.get_logger().info("FMS Node initialized")

        self._registered_robots: set[str] = set()

        # 연결되어 한 번이라도 등록된 로봇의 Publisher, Subscription, ActionClient를 관리
        self._cmd_vel_publishers: dict[str, Publisher] = {}

        self._battery_subscribers: dict[str, Subscription] = {}
        self._pose_subscribers: dict[str, Subscription] = {}

        self._follow_waypoints_clients: dict[str, ActionClient] = {}
        self._precision_dock_clients: dict[str, ActionClient] = {}
        self._aruco_clients: dict[str, ActionClient] = {}

        # 현재 실행 중인 FollowWaypoints Goal 관리
        self._follow_waypoints_goal_handles = {}
        self._follow_waypoints_pending: set[str] = set()
        self._precision_dock_goal_handles = {}
        self._precision_dock_pending: set[str] = set()
        self._aruco_goal_handles = {}
        self._aruco_pending: set[str] = set()
        self._aruco_context: dict[str, dict] = {}
        self._follow_cancel_after_accept: dict[str, list] = {}
        self._dock_cancel_after_accept: dict[str, list] = {}
        self._aruco_cancel_after_accept: dict[str, list] = {}
        self._action_lock = RLock()

        self.navigation_result_callback = None
        self.precision_dock_result_callback = None
        self.aruco_result_callback = None

    def register_robot(self, robot_id: str) -> None:

        # 이미 등록되어 있으면 새로 만들지 않음
        if robot_id in self._registered_robots:
            return

        # 발행
        publisher_cmd_vel = self.create_publisher(TwistStamped, f"/{robot_id}/cmd_vel", 10)

        # # 구독
        # subscription_pose = self.create_subscription(
        #     PoseWithCovarianceStamped,
        #     f"/{robot_id}/amcl_pose",
        #     # "ROS 메시지 msg가 들어오면, 이 Subscriber를 만들 당시의 robot_id와 함께 함수 호출
        #     lambda msg, rid=robot_id: self._on_amcl_pose(rid, msg),
        #     10,
        # )

        # 구독
        subscription_pose = self.create_subscription(
            PoseStamped,
            f"/{robot_id}/logitle_pose",
            # "ROS 메시지 msg가 들어오면, 이 Subscriber를 만들 당시의 robot_id와 함께 함수 호출
            lambda msg, rid=robot_id: self._on_amcl_pose(rid, msg),
            10,
        )

        subscription_battery = self.create_subscription(
            BatteryState,
            f"/{robot_id}/battery_state",
            # "ROS 메시지 msg가 들어오면, 이 Subscriber를 만들 당시의 robot_id와 함께 함수 호출
            lambda msg, rid=robot_id: self._on_battery_state(rid, msg),
            10,
        )

        # 액션 클라이언트
        action_follow_waypoints_client = ActionClient(
            self, FollowWaypoints, f"/{robot_id}/follow_waypoints"
        )

        action_precision_dock_client = ActionClient(
            self, PrecisionDock, f"/{robot_id}/precision_dock"
        )

        action_aruco_client = None
        if AlignAndCorrectWithAruco is not None:
            action_aruco_client = ActionClient(
                self,
                AlignAndCorrectWithAruco,
                f"/{robot_id}/aruco_align_and_correct",
            )

        # 딕셔너리에서 관리
        self._cmd_vel_publishers[robot_id] = publisher_cmd_vel
        self._pose_subscribers[robot_id] = subscription_pose
        self._battery_subscribers[robot_id] = subscription_battery
        self._follow_waypoints_clients[robot_id] = action_follow_waypoints_client
        self._precision_dock_clients[robot_id] = action_precision_dock_client
        if action_aruco_client is not None:
            self._aruco_clients[robot_id] = action_aruco_client

        # 모든 인터페이스 생성이 끝난 후 등록 처리
        self._registered_robots.add(robot_id)
        self.get_logger().info(f"Robot registered: {robot_id}")
        logger.info(
            "event=ros_interfaces_registered robot_id=%s pose_topic=/%s/logitle_pose "
            "battery_topic=/%s/battery_state cmd_vel_topic=/%s/cmd_vel",
            robot_id,
            robot_id,
            robot_id,
            robot_id,
        )

    def is_registered(self, robot_id: str) -> bool:
        return robot_id in self._registered_robots

    def has_active_navigation(self, robot_id: str) -> bool:
        with self._action_lock:
            return (
                robot_id in self._follow_waypoints_pending
                or robot_id in self._follow_waypoints_goal_handles
            )

    def has_active_docking(self, robot_id: str) -> bool:
        with self._action_lock:
            return (
                robot_id in self._precision_dock_pending
                or robot_id in self._precision_dock_goal_handles
            )

    def has_active_aruco(self, robot_id: str) -> bool:
        with self._action_lock:
            return (
                robot_id in self._aruco_pending
                or robot_id in self._aruco_goal_handles
            )

    def has_active_action(self, robot_id: str) -> bool:
        return (
            self.has_active_navigation(robot_id)
            or self.has_active_docking(robot_id)
            or self.has_active_aruco(robot_id)
        )

    def clear_robot_action_state(self, robot_id: str) -> None:
        """로봇이 완전히 오프라인이 된 뒤 남은 로컬 goal handle을 제거한다."""
        with self._action_lock:
            had_navigation = (
                robot_id in self._follow_waypoints_pending
                or robot_id in self._follow_waypoints_goal_handles
            )
            had_docking = (
                robot_id in self._precision_dock_pending
                or robot_id in self._precision_dock_goal_handles
            )
            had_aruco = (
                robot_id in self._aruco_pending
                or robot_id in self._aruco_goal_handles
            )
            self._follow_waypoints_pending.discard(robot_id)
            self._follow_waypoints_goal_handles.pop(robot_id, None)
            self._precision_dock_pending.discard(robot_id)
            self._precision_dock_goal_handles.pop(robot_id, None)
            self._aruco_pending.discard(robot_id)
            self._aruco_goal_handles.pop(robot_id, None)
            self._aruco_context.pop(robot_id, None)
            pending_callbacks = (
                self._follow_cancel_after_accept.pop(robot_id, [])
                + self._dock_cancel_after_accept.pop(robot_id, [])
                + self._aruco_cancel_after_accept.pop(robot_id, [])
            )
        for callback in pending_callbacks:
            callback(False)
        if had_navigation or had_docking or had_aruco:
            logger.warning(
                "event=stale_action_state_cleared robot_id=%s navigation=%s docking=%s aruco=%s",
                robot_id,
                had_navigation,
                had_docking,
                had_aruco,
            )

    def _quaternion_to_yaw(self, q: Quaternion) -> float:
        siny_cosp = 2.0 * (q.w * q.z + q.x * q.y)
        cosy_cosp = 1.0 - 2.0 * (q.y * q.y + q.z * q.z)

        return math.atan2(siny_cosp, cosy_cosp)

    def publish_cmd_vel(self, robot_id: str, linear_x: float, angular_z: float) -> None:
        publisher = self._cmd_vel_publishers.get(robot_id)
        if publisher is None:
            raise ValueError(f"Robot is not registered: {robot_id}")

        message = TwistStamped()
        message.header.stamp = self.get_clock().now().to_msg()
        message.twist.linear.x = float(linear_x)
        message.twist.angular.z = float(angular_z)

        publisher.publish(message)

    def send_follow_waypoints_goal(
        self, robot_id: str, waypoints: list[tuple[float, float, float]]
    ) -> None:
        client = self._follow_waypoints_clients.get(robot_id)
        if client is None:
            raise ValueError(f"Robot is not registered: {robot_id}")

        # Nav2 FollowWaypoints Action Server 연결 확인
        if not client.wait_for_server(timeout_sec=2.0):
            logger.warning(
                "event=navigation_server_unavailable robot_id=%s action=follow_waypoints",
                robot_id,
            )
            raise RuntimeError(f"FollowWaypoints Action Server를 찾을 수 없습니다: {robot_id}")

        # FollowWaypoints Goal 생성
        goal = FollowWaypoints.Goal()
        poses = []

        for x, y, yaw in waypoints:
            pose = PoseStamped()

            pose.header.frame_id = "map"
            pose.header.stamp = self.get_clock().now().to_msg()

            pose.pose.position.x = float(x)
            pose.pose.position.y = float(y)

            # 기존 PoseStamped 생성 및 위치 설정 유지
            pose.pose.orientation.x = 0.0
            pose.pose.orientation.y = 0.0
            pose.pose.orientation.z = math.sin(yaw / 2.0)
            pose.pose.orientation.w = math.cos(yaw / 2.0)

            poses.append(pose)

        goal.poses = poses

        # 비동기로 Goal 전송
        with self._action_lock:
            if self.has_active_navigation(robot_id):
                raise RuntimeError(f"FollowWaypoints goal이 이미 진행 중입니다: {robot_id}")
            self._follow_waypoints_pending.add(robot_id)

        try:
            future = client.send_goal_async(
                goal,
                feedback_callback=lambda feedback, rid=robot_id: self._on_follow_waypoints_feedback(
                    rid, feedback
                ),
            )
        except Exception:
            with self._action_lock:
                self._follow_waypoints_pending.discard(robot_id)
            raise
        logger.info(
            "event=navigation_goal_sent robot_id=%s waypoint_count=%s",
            robot_id,
            len(poses),
        )

        future.add_done_callback(
            lambda future, rid=robot_id: self._on_follow_waypoints_goal_response(rid, future)
        )

    def _on_follow_waypoints_goal_response(self, robot_id: str, future) -> None:
        with self._action_lock:
            was_pending = robot_id in self._follow_waypoints_pending
            self._follow_waypoints_pending.discard(robot_id)
            cancel_callbacks = self._follow_cancel_after_accept.pop(robot_id, [])
        try:
            goal_handle = future.result()
        except Exception:
            logger.exception(
                "event=navigation_goal_response_failed robot_id=%s", robot_id
            )
            for callback in cancel_callbacks:
                callback(True)
            if not cancel_callbacks and self.navigation_result_callback:
                self.navigation_result_callback(robot_id, GoalStatus.STATUS_ABORTED)
            return

        if not was_pending:
            logger.warning(
                "event=navigation_late_goal_response robot_id=%s accepted=%s",
                robot_id,
                goal_handle.accepted,
            )
            if goal_handle.accepted:
                goal_handle.cancel_goal_async()
            for callback in cancel_callbacks:
                callback(False)
            return

        if not goal_handle.accepted:
            self.get_logger().warning(f"FollowWaypoints goal rejected: {robot_id}")
            logger.warning("event=navigation_goal_rejected robot_id=%s", robot_id)
            for callback in cancel_callbacks:
                callback(True)
            if not cancel_callbacks and self.navigation_result_callback:
                self.navigation_result_callback(robot_id, GoalStatus.STATUS_ABORTED)
            return
        # 현재 실행 중인 Goal 저장
        with self._action_lock:
            self._follow_waypoints_goal_handles[robot_id] = goal_handle

        self.get_logger().info(f"FollowWaypoints goal accepted: {robot_id}")
        logger.info("event=navigation_goal_accepted robot_id=%s", robot_id)

        result_future = goal_handle.get_result_async()

        result_future.add_done_callback(
            lambda future, rid=robot_id, handle=goal_handle: self._on_follow_waypoints_result(
                rid, handle, future
            )
        )

        if cancel_callbacks:
            self.cancel_follow_waypoints(
                robot_id,
                lambda success: [callback(success) for callback in cancel_callbacks],
            )

    def _on_follow_waypoints_result(self, robot_id: str, goal_handle, future) -> None:
        try:
            result = future.result()
        except Exception:
            logger.exception("event=navigation_result_failed robot_id=%s", robot_id)
            with self._action_lock:
                current_handle = self._follow_waypoints_goal_handles.get(robot_id)
                if current_handle is goal_handle:
                    self._follow_waypoints_goal_handles.pop(robot_id, None)
            if self.navigation_result_callback:
                self.navigation_result_callback(robot_id, GoalStatus.STATUS_ABORTED)
            return

        # 종료된 Goal이 현재 실행 중인 Goal일 때만 삭제
        with self._action_lock:
            current_handle = self._follow_waypoints_goal_handles.get(robot_id)
            if current_handle is goal_handle:
                self._follow_waypoints_goal_handles.pop(robot_id, None)
            else:
                return

        self.get_logger().info(f"FollowWaypoints finished: {robot_id}, " f"status={result.status}")
        logger.info(
            "event=navigation_finished robot_id=%s status=%s", robot_id, result.status
        )

        if self.navigation_result_callback:
            self.navigation_result_callback(robot_id, result.status)

    def _on_follow_waypoints_feedback(self, robot_id: str, feedback_msg) -> None:
        feedback = feedback_msg.feedback

        self.get_logger().info(
            f"FollowWaypoints feedback: {robot_id}, "
            f"current_waypoint={feedback.current_waypoint}"
        )

    def cancel_follow_waypoints(self, robot_id: str, callback=None) -> None:
        with self._action_lock:
            goal_handle = self._follow_waypoints_goal_handles.get(robot_id)
            pending = robot_id in self._follow_waypoints_pending

        if pending and goal_handle is None:
            if callback:
                with self._action_lock:
                    self._follow_cancel_after_accept.setdefault(robot_id, []).append(callback)
            logger.info("event=navigation_cancel_queued robot_id=%s", robot_id)
            return

        # 실행 중인 Goal이 없으면 바로 다음 작업
        if goal_handle is None:
            if callback:
                callback(True)
            return

        self.get_logger().info(f"FollowWaypoints cancel requested: {robot_id}")

        future = goal_handle.cancel_goal_async()
        future.add_done_callback(
            lambda future, rid=robot_id, handle=goal_handle: self._on_follow_waypoints_cancel(
                rid, handle, future, callback
            )
        )

    def _on_follow_waypoints_cancel(
        self, robot_id: str, goal_handle, future, callback=None
    ) -> None:
        try:
            response = future.result()
        except Exception:
            logger.exception("event=navigation_cancel_failed robot_id=%s", robot_id)
            if callback:
                callback(False)
            return

        if not response.goals_canceling:
            self.get_logger().warning(f"FollowWaypoints cancel failed: {robot_id}")
            logger.warning(
                "event=navigation_cancel_rejected robot_id=%s", robot_id
            )
            if callback:
                callback(False)
            return

        self.get_logger().info(f"FollowWaypoints cancel accepted: {robot_id}")

        with self._action_lock:
            current_handle = self._follow_waypoints_goal_handles.get(robot_id)
            if current_handle is goal_handle:
                self._follow_waypoints_goal_handles.pop(robot_id, None)

        if callback:
            callback(True)

    def send_precision_dock(self, robot_id):
        client = self._precision_dock_clients.get(robot_id)

        if client is None:
            print(f"[Error] [Robot {robot_id}] PrecisionDock client not available: {robot_id}")
            raise ValueError(f"PrecisionDock client not found: {robot_id}")

        if self.has_active_docking(robot_id):
            raise RuntimeError(f"PrecisionDock goal이 이미 진행 중입니다: {robot_id}")

        logger.info(
            "event=precision_dock_server_check robot_id=%s ready=%s",
            robot_id,
            client.server_is_ready(),
        )
        if not client.wait_for_server(timeout_sec=2.0):
            logger.warning("event=precision_dock_server_unavailable robot_id=%s", robot_id)
            if self.precision_dock_result_callback:
                self.precision_dock_result_callback(robot_id, GoalStatus.STATUS_ABORTED)

            return

        goal = PrecisionDock.Goal()

        goal.target_pose.header.frame_id = "base_link"
        goal.target_pose.pose.position.x = 0.0
        goal.target_pose.pose.position.y = 0.0
        goal.target_pose.pose.position.z = 0.0
        goal.target_pose.pose.orientation.w = 1.0

        with self._action_lock:
            self._precision_dock_pending.add(robot_id)
        try:
            future = client.send_goal_async(goal)
        except Exception:
            with self._action_lock:
                self._precision_dock_pending.discard(robot_id)
            logger.exception("event=precision_dock_goal_send_failed robot_id=%s", robot_id)
            if self.precision_dock_result_callback:
                self.precision_dock_result_callback(robot_id, GoalStatus.STATUS_ABORTED)
            return
        future.add_done_callback(
            lambda future: self._on_precision_dock_goal_response(robot_id, future)
        )

    def cancel_precision_dock(self, robot_id: str, callback=None) -> None:
        with self._action_lock:
            goal_handle = self._precision_dock_goal_handles.get(robot_id)
            pending = robot_id in self._precision_dock_pending
        if pending and goal_handle is None:
            if callback:
                with self._action_lock:
                    self._dock_cancel_after_accept.setdefault(robot_id, []).append(callback)
            logger.info("event=precision_dock_cancel_queued robot_id=%s", robot_id)
            return
        if goal_handle is None:
            if callback:
                callback(True)
            return

        future = goal_handle.cancel_goal_async()

        def finish_cancel(done_future) -> None:
            try:
                response = done_future.result()
            except Exception:
                logger.exception("event=precision_dock_cancel_failed robot_id=%s", robot_id)
                if callback:
                    callback(False)
                return
            if not response.goals_canceling:
                logger.warning("event=precision_dock_cancel_rejected robot_id=%s", robot_id)
                if callback:
                    callback(False)
                return
            with self._action_lock:
                current = self._precision_dock_goal_handles.get(robot_id)
                if current is goal_handle:
                    self._precision_dock_goal_handles.pop(robot_id, None)
            logger.info("event=precision_dock_cancel_accepted robot_id=%s", robot_id)
            if callback:
                callback(True)

        future.add_done_callback(finish_cancel)

    def _on_precision_dock_goal_response(self, robot_id: str, future) -> None:
        with self._action_lock:
            was_pending = robot_id in self._precision_dock_pending
            self._precision_dock_pending.discard(robot_id)
            cancel_callbacks = self._dock_cancel_after_accept.pop(robot_id, [])
        try:
            goal_handle = future.result()
        except Exception:
            logger.exception("event=precision_dock_goal_response_failed robot_id=%s", robot_id)
            for callback in cancel_callbacks:
                callback(True)
            if not cancel_callbacks and self.precision_dock_result_callback:
                self.precision_dock_result_callback(robot_id, GoalStatus.STATUS_ABORTED)
            return


        if not was_pending:
            logger.warning(
                "event=precision_dock_late_goal_response robot_id=%s accepted=%s",
                robot_id,
                goal_handle.accepted,
            )
            if goal_handle.accepted:
                goal_handle.cancel_goal_async()
            for callback in cancel_callbacks:
                callback(False)
            return

        if not goal_handle.accepted:
            logger.warning("event=precision_dock_goal_rejected robot_id=%s", robot_id)

            for callback in cancel_callbacks:
                callback(True)
            if not cancel_callbacks and self.precision_dock_result_callback:
                self.precision_dock_result_callback(robot_id, GoalStatus.STATUS_ABORTED)
            return

        with self._action_lock:
            self._precision_dock_goal_handles[robot_id] = goal_handle
        logger.info("event=precision_dock_goal_accepted robot_id=%s", robot_id)

        result_future = goal_handle.get_result_async()

        result_future.add_done_callback(
            lambda future, rid=robot_id, handle=goal_handle: self._on_precision_dock_result(
                rid, handle, future
            )
        )

        if cancel_callbacks:
            self.cancel_precision_dock(
                robot_id,
                lambda success: [callback(success) for callback in cancel_callbacks],
            )

    def _on_precision_dock_result(self, robot_id: str, goal_handle, future) -> None:
        try:
            result = future.result()
        except Exception:
            logger.exception("event=precision_dock_result_failed robot_id=%s", robot_id)
            result_status = GoalStatus.STATUS_ABORTED
        else:
            result_status = result.status

        with self._action_lock:
            current_handle = self._precision_dock_goal_handles.get(robot_id)
            if current_handle is goal_handle:
                self._precision_dock_goal_handles.pop(robot_id, None)
            else:
                return

        logger.info(
            "event=precision_dock_finished robot_id=%s status=%s",
            robot_id,
            result_status,
        )

        if self.precision_dock_result_callback:
            self.precision_dock_result_callback(robot_id, result_status)

    def send_aruco_alignment(self, robot_id: str, node_id: str, marker_id: int) -> None:
        if AlignAndCorrectWithAruco is None:
            raise RuntimeError(
                "메인 PC에 logitle_aruco_msgs 인터페이스가 설치되어 있지 않습니다."
            )

        client = self._aruco_clients.get(robot_id)
        if client is None:
            raise ValueError(f"ArUco Action client를 찾을 수 없습니다: {robot_id}")
        if self.has_active_aruco(robot_id):
            raise RuntimeError(f"ArUco 정렬이 이미 진행 중입니다: {robot_id}")
        if not client.wait_for_server(timeout_sec=2.0):
            raise RuntimeError(f"ArUco Action Server를 찾을 수 없습니다: {robot_id}")

        goal = AlignAndCorrectWithAruco.Goal()
        goal.marker_id = int(marker_id)
        goal.apply_correction = True

        with self._action_lock:
            self._aruco_pending.add(robot_id)
            self._aruco_context[robot_id] = {
                "node_id": str(node_id),
                "marker_id": int(marker_id),
            }

        try:
            future = client.send_goal_async(
                goal,
                feedback_callback=lambda feedback, rid=robot_id: self._on_aruco_feedback(
                    rid, feedback
                ),
            )
        except Exception:
            with self._action_lock:
                self._aruco_pending.discard(robot_id)
                self._aruco_context.pop(robot_id, None)
            raise

        logger.info(
            "event=aruco_goal_sent robot_id=%s node_id=%s marker_id=%s",
            robot_id,
            node_id,
            marker_id,
        )
        future.add_done_callback(
            lambda done, rid=robot_id: self._on_aruco_goal_response(rid, done)
        )

    def _on_aruco_goal_response(self, robot_id: str, future) -> None:
        with self._action_lock:
            was_pending = robot_id in self._aruco_pending
            self._aruco_pending.discard(robot_id)
            cancel_callbacks = self._aruco_cancel_after_accept.pop(robot_id, [])
        try:
            goal_handle = future.result()
        except Exception:
            logger.exception("event=aruco_goal_response_failed robot_id=%s", robot_id)
            for callback in cancel_callbacks:
                callback(True)
            if not cancel_callbacks:
                self._notify_aruco_failure(robot_id, 4)
            return

        if not was_pending:
            if goal_handle.accepted:
                goal_handle.cancel_goal_async()
            for callback in cancel_callbacks:
                callback(False)
            return
        if not goal_handle.accepted:
            logger.warning("event=aruco_goal_rejected robot_id=%s", robot_id)
            for callback in cancel_callbacks:
                callback(True)
            if not cancel_callbacks:
                self._notify_aruco_failure(robot_id, 4)
            return

        with self._action_lock:
            self._aruco_goal_handles[robot_id] = goal_handle
        logger.info("event=aruco_goal_accepted robot_id=%s", robot_id)
        result_future = goal_handle.get_result_async()
        result_future.add_done_callback(
            lambda done, rid=robot_id, handle=goal_handle: self._on_aruco_result(
                rid, handle, done
            )
        )

        if cancel_callbacks:
            self.cancel_aruco_alignment(
                robot_id,
                lambda success: [callback(success) for callback in cancel_callbacks],
            )

    def _on_aruco_result(self, robot_id: str, goal_handle, future) -> None:
        try:
            wrapped_result = future.result()
            status = wrapped_result.status
            result = wrapped_result.result
            details = {
                "success": bool(getattr(result, "success", False)),
                "result_code": int(getattr(result, "result_code", -1)),
                "align_success": bool(getattr(result, "align_success", False)),
                "correction_success": bool(
                    getattr(result, "correction_success", False)
                ),
                "correction_result_code": int(
                    getattr(result, "correction_result_code", -1)
                ),
            }
        except Exception:
            logger.exception("event=aruco_result_failed robot_id=%s", robot_id)
            status = GoalStatus.STATUS_ABORTED
            details = {"success": False, "result_code": 4}

        with self._action_lock:
            current = self._aruco_goal_handles.get(robot_id)
            if current is not goal_handle:
                return
            self._aruco_goal_handles.pop(robot_id, None)
            context = self._aruco_context.pop(robot_id, {})

        logger.info(
            "event=aruco_finished robot_id=%s node_id=%s status=%s details=%s",
            robot_id,
            context.get("node_id"),
            status,
            details,
        )
        if self.aruco_result_callback:
            self.aruco_result_callback(robot_id, context.get("node_id"), status, details)

    def _notify_aruco_failure(self, robot_id: str, result_code: int) -> None:
        with self._action_lock:
            context = self._aruco_context.pop(robot_id, {})
        if self.aruco_result_callback:
            self.aruco_result_callback(
                robot_id,
                context.get("node_id"),
                GoalStatus.STATUS_ABORTED,
                {"success": False, "result_code": result_code},
            )

    def _on_aruco_feedback(self, robot_id: str, feedback_msg) -> None:
        logger.debug("event=aruco_feedback robot_id=%s", robot_id)

    def cancel_aruco_alignment(self, robot_id: str, callback=None) -> None:
        with self._action_lock:
            goal_handle = self._aruco_goal_handles.get(robot_id)
            pending = robot_id in self._aruco_pending
        if pending and goal_handle is None:
            if callback:
                with self._action_lock:
                    self._aruco_cancel_after_accept.setdefault(robot_id, []).append(callback)
            logger.info("event=aruco_cancel_queued robot_id=%s", robot_id)
            return
        if goal_handle is None:
            if callback:
                callback(True)
            return

        future = goal_handle.cancel_goal_async()

        def finish_cancel(done_future) -> None:
            try:
                response = done_future.result()
            except Exception:
                logger.exception("event=aruco_cancel_failed robot_id=%s", robot_id)
                if callback:
                    callback(False)
                return
            if not response.goals_canceling:
                logger.warning("event=aruco_cancel_rejected robot_id=%s", robot_id)
                if callback:
                    callback(False)
                return
            with self._action_lock:
                current = self._aruco_goal_handles.get(robot_id)
                if current is goal_handle:
                    self._aruco_goal_handles.pop(robot_id, None)
                self._aruco_context.pop(robot_id, None)
            logger.info("event=aruco_cancel_accepted robot_id=%s", robot_id)
            if callback:
                callback(True)

        future.add_done_callback(finish_cancel)

    def cancel_all_actions(self, robot_id: str, callback) -> None:
        """현재 액션들을 모두 취소한 뒤 callback(success)을 한 번 호출한다."""
        remaining = 3
        results: list[bool] = []
        result_lock = RLock()

        def action_finished(success: bool) -> None:
            nonlocal remaining
            with result_lock:
                results.append(success)
                remaining -= 1
                if remaining == 0:
                    callback(all(results))

        self.cancel_follow_waypoints(robot_id, action_finished)
        self.cancel_precision_dock(robot_id, action_finished)
        self.cancel_aruco_alignment(robot_id, action_finished)

    def _on_amcl_pose(self, robot_id: str, msg: PoseStamped) -> None:
        robot = fleet_manager.get_robot(robot_id)
        if robot is None:
            return

        robot.update_pose(
            x=msg.pose.position.x,
            y=msg.pose.position.y,
            yaw=self._quaternion_to_yaw(msg.pose.orientation),
        )

    def _on_battery_state(self, robot_id: str, msg: BatteryState) -> None:
        robot = fleet_manager.get_robot(robot_id)
        if robot is None:
            return
        robot.update_battery(percentage=msg.percentage)


def main(args=None):
    rp.init(args=args)
    node = FmsRosNode()

    try:
        rp.spin(node)

    except KeyboardInterrupt:
        pass

    finally:
        node.destroy_node()
        rp.shutdown()


if __name__ == "__main__":
    main()
