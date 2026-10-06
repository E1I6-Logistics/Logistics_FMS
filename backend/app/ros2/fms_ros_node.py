from __future__ import annotations

import rclpy as rp
from rclpy.node import Node
import math
from functools import wraps
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
from logitle_aruco_msgs.action import AlignAndCorrectWithAruco


def _navigation_locked(method):
    @wraps(method)
    def locked(self, *args, **kwargs):
        with self.navigation_lock:
            return method(self, *args, **kwargs)

    return locked


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
        self._aruco_align_clients: dict[str, ActionClient] = {}

        # 현재 실행 중인 FollowWaypoints Goal 관리
        self._follow_waypoints_goal_handles = {}
        # Goal 수락 대기 중에도 취소 요청을 기억한다. 콜백은 terminal result 뒤 실행
        self._follow_waypoints_pending = set()
        self._follow_waypoints_cancel_callbacks = {}
        self._follow_waypoints_feedback_tokens = {}
        self.navigation_lock = RLock()

        self.navigation_result_callback = None
        self.navigation_error_callback = None
        self.precision_dock_result_callback = None
        self.aruco_align_result_callback = None

    def register_robot(self, robot_id: str) -> None:

        # 이미 등록되어 있으면 새로 만들지 않음
        if robot_id in self._registered_robots:
            return

        # 발행
        publisher_cmd_vel = self.create_publisher(TwistStamped, f"/{robot_id}/cmd_vel", 10)

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

        action_aruco_align_client = ActionClient(
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
        self._aruco_align_clients[robot_id] = action_aruco_align_client

        # 모든 인터페이스 생성이 끝난 후 등록 처리
        self._registered_robots.add(robot_id)
        self.get_logger().info(f"Robot registered: {robot_id}")

    def is_registered(self, robot_id: str) -> bool:
        return robot_id in self._registered_robots

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

    @_navigation_locked
    def send_follow_waypoints_goal(
        self, robot_id: str, waypoints: list[tuple[float, float, float]]
    ) -> None:
        client = self._follow_waypoints_clients.get(robot_id)
        if client is None:
            raise ValueError(f"Robot is not registered: {robot_id}")

        if (
            robot_id in self._follow_waypoints_pending
            or robot_id in self._follow_waypoints_goal_handles
        ):
            raise RuntimeError(f"이전 FollowWaypoints 실행이 종료되지 않았습니다: {robot_id}")

        # Nav2 FollowWaypoints Action Server 연결 확인
        if not client.wait_for_server(timeout_sec=2.0):
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
        token = object()
        self._follow_waypoints_feedback_tokens[robot_id] = token
        self._follow_waypoints_pending.add(robot_id)
        try:
            future = client.send_goal_async(
                goal,
                feedback_callback=lambda feedback, rid=robot_id, expected=token: self._on_follow_waypoints_feedback(
                    rid, feedback, expected
                ),
            )
        except Exception:
            self._follow_waypoints_pending.discard(robot_id)
            self._follow_waypoints_feedback_tokens.pop(robot_id, None)
            raise

        future.add_done_callback(
            lambda future, rid=robot_id: self._on_follow_waypoints_goal_response(rid, future)
        )

    def _navigation_error(self, robot_id: str, reason: str) -> None:
        self.get_logger().error(f"FollowWaypoints error: {robot_id}, reason={reason}")
        if getattr(self, "navigation_error_callback", None):
            self.navigation_error_callback(robot_id, reason)

    @_navigation_locked
    def _on_follow_waypoints_goal_response(self, robot_id: str, future) -> None:
        try:
            goal_handle = future.result()
        except Exception as exc:
            # 서버가 수락했는지 알 수 없으므로 pending을 지우고 새 Goal을 보내면 안 된다.
            self._navigation_error(robot_id, f"goal_response_error:{exc}")
            return
        self._follow_waypoints_pending.discard(robot_id)

        if not goal_handle.accepted:
            self._follow_waypoints_feedback_tokens.pop(robot_id, None)
            callback = self._follow_waypoints_cancel_callbacks.pop(robot_id, None)
            if callback is not None:
                callback()
                return
            self.get_logger().warning(f"FollowWaypoints goal rejected: {robot_id}")
            if self.navigation_result_callback:
                self.navigation_result_callback(robot_id, GoalStatus.STATUS_ABORTED)
            return

        # 현재 실행 중인 Goal 저장
        self._follow_waypoints_goal_handles[robot_id] = goal_handle

        self.get_logger().info(f"FollowWaypoints goal accepted: {robot_id}")

        try:
            result_future = goal_handle.get_result_async()
            result_future.add_done_callback(
                lambda future, rid=robot_id, handle=goal_handle: self._on_follow_waypoints_result(
                    rid, handle, future
                )
            )
        except Exception as exc:
            self._navigation_error(robot_id, f"result_subscription_error:{exc}")
            return
        if robot_id in self._follow_waypoints_cancel_callbacks:
            self.cancel_follow_waypoints(
                robot_id, self._follow_waypoints_cancel_callbacks[robot_id]
            )

    @_navigation_locked
    def _on_follow_waypoints_result(self, robot_id: str, goal_handle, future) -> None:
        # 이전 Goal의 Future가 실패했어도 현재 Goal에는 영향을 주지 않는다.
        if self._follow_waypoints_goal_handles.get(robot_id) is not goal_handle:
            return
        try:
            result = future.result()
        except Exception as exc:
            self._navigation_error(robot_id, f"result_error:{exc}")
            return
        self._follow_waypoints_goal_handles.pop(robot_id, None)
        self._follow_waypoints_feedback_tokens.pop(robot_id, None)

        self.get_logger().info(f"FollowWaypoints finished: {robot_id}, " f"status={result.status}")

        callback = self._follow_waypoints_cancel_callbacks.pop(robot_id, None)
        if callback is not None:
            callback()
        elif self.navigation_result_callback:
            status = result.status
            # FollowWaypoints가 완료되어도 건너뛴 waypoint가 있으면 도착 성공이 아니다.
            if status == GoalStatus.STATUS_SUCCEEDED and getattr(
                    getattr(result, "result", None), "missed_waypoints", []):
                status = GoalStatus.STATUS_ABORTED
            self.navigation_result_callback(robot_id, status)

    @_navigation_locked
    def _on_follow_waypoints_feedback(self, robot_id: str, feedback_msg, token=None) -> None:
        if token is not None and self._follow_waypoints_feedback_tokens.get(robot_id) is not token:
            return  # 이전 Goal의 늦은 Feedback은 새 경로 인덱스를 바꾸지 않는다.
        feedback = feedback_msg.feedback

        self.get_logger().info(
            f"FollowWaypoints feedback: {robot_id}, "
            f"current_waypoint={feedback.current_waypoint}"
        )
        # 점유 확정은 Pose에서만 한다. Feedback은 현재 Goal의 진행 순서만 전달한다.
        if getattr(self, "navigation_feedback_callback", None):
            self.navigation_feedback_callback(robot_id, feedback.current_waypoint)

    @_navigation_locked
    def cancel_follow_waypoints(self, robot_id: str, callback=None) -> None:
        callback = callback or (lambda: None)
        self._follow_waypoints_cancel_callbacks[robot_id] = callback
        if robot_id in self._follow_waypoints_pending:
            return
        goal_handle = self._follow_waypoints_goal_handles.get(robot_id)

        # 실행 중인 Goal이 없으면 바로 다음 작업
        if goal_handle is None:
            self._follow_waypoints_cancel_callbacks.pop(robot_id, None)
            callback()
            return

        self.get_logger().info(f"FollowWaypoints cancel requested: {robot_id}")

        try:
            future = goal_handle.cancel_goal_async()
            future.add_done_callback(
                lambda future, rid=robot_id, handle=goal_handle: self._on_follow_waypoints_cancel(
                    rid, handle, future, callback
                )
            )
        except Exception as exc:
            self._navigation_error(robot_id, f"cancel_send_error:{exc}")

    @_navigation_locked
    def _on_follow_waypoints_cancel(
        self, robot_id: str, goal_handle, future, callback=None
    ) -> None:
        if self._follow_waypoints_goal_handles.get(robot_id) is not goal_handle:
            return
        try:
            response = future.result()
        except Exception as exc:
            self._navigation_error(robot_id, f"cancel_response_error:{exc}")
            return
        if not response.goals_canceling:
            self._navigation_error(robot_id, "cancel_rejected")
            return

        self.get_logger().info(f"FollowWaypoints cancel accepted: {robot_id}")

        # 취소 수락은 실행 종료가 아니다. handle과 예약은 result 수신까지 유지한다.

    def send_precision_dock(self, robot_id):
        client = self._precision_dock_clients.get(robot_id)

        if client is None:
            print(f"[Error] [Robot {robot_id}] PrecisionDock client not available: {robot_id}")
            raise ValueError(f"PrecisionDock client not found: {robot_id}")

        print(f"[DEBUG] PrecisionDock {robot_id}: " f"ready={client.server_is_ready()}")
        if not client.wait_for_server(timeout_sec=2.0):
            print(f"[Error] [Robot {robot_id}] PrecisionDock server not available: {robot_id}")
            if self.precision_dock_result_callback:
                self.precision_dock_result_callback(robot_id, GoalStatus.STATUS_ABORTED)

            return

        goal = PrecisionDock.Goal()

        goal.target_pose.header.frame_id = "base_link"
        goal.target_pose.pose.position.x = 0.0
        goal.target_pose.pose.position.y = 0.0
        goal.target_pose.pose.position.z = 0.0
        goal.target_pose.pose.orientation.w = 1.0

        future = client.send_goal_async(goal)
        future.add_done_callback(
            lambda future: self._on_precision_dock_goal_response(robot_id, future)
        )

    def _on_precision_dock_goal_response(self, robot_id: str, future) -> None:
        goal_handle = future.result()

        if not goal_handle.accepted:
            print(f"[Error] [Robot {robot_id}] PrecisionDock goal rejected: {robot_id}")

            if self.precision_dock_result_callback:
                self.precision_dock_result_callback(robot_id, GoalStatus.STATUS_ABORTED)
            return

        print(f"[Info] [Robot {robot_id}] PrecisionDock goal accepted: {robot_id}")

        result_future = goal_handle.get_result_async()

        result_future.add_done_callback(
            lambda future, rid=robot_id: self._on_precision_dock_result(rid, future)
        )

    def _on_precision_dock_result(self, robot_id: str, future) -> None:
        result = future.result()

        print(
            f"[Info] [Robot {robot_id}] PrecisionDock finished: {robot_id}, status={result.status}"
        )

        if self.precision_dock_result_callback:
            self.precision_dock_result_callback(robot_id, result.status)

    def send_aruco_align(self, robot_id: str, marker_id: int) -> None:
        client = self._aruco_align_clients.get(robot_id)

        if client is None:
            raise ValueError(f"Aruco Align Action client를 찾을 수 없습니다: {robot_id}")

        # Action Server 연결 확인
        if not client.wait_for_server(timeout_sec=2.0):
            print(f"[Error] [{robot_id}] " f"Aruco Align Action Server를 찾을 수 없습니다.")

            if self.aruco_align_result_callback:
                self.aruco_align_result_callback(robot_id, GoalStatus.STATUS_ABORTED)

            return

        # Goal 생성
        goal = AlignAndCorrectWithAruco.Goal()
        goal.marker_id = int(marker_id)
        goal.apply_correction = True

        print(f"[ARUCO] Goal 전송: " f"robot={robot_id}, marker_id={marker_id}")

        # Feedback callback은 사용하지 않음
        future = client.send_goal_async(goal)
        future.add_done_callback(
            lambda future, rid=robot_id: self._on_aruco_align_goal_response(rid, future)
        )

    def _on_aruco_align_goal_response(self, robot_id: str, future) -> None:
        goal_handle = future.result()

        if not goal_handle.accepted:
            print(f"[ARUCO] Goal 거부: {robot_id}")

            if self.aruco_align_result_callback:
                self.aruco_align_result_callback(robot_id, GoalStatus.STATUS_ABORTED)

            return

        print(f"[ARUCO] Goal 수락: {robot_id}")

        result_future = goal_handle.get_result_async()

        result_future.add_done_callback(
            lambda future, rid=robot_id: self._on_aruco_align_result(rid, future)
        )

    def _on_aruco_align_result(self, robot_id: str, future) -> None:
        result = future.result()
        print(f"[ARUCO] 완료: " f"robot={robot_id}, status={result.status}")

        if self.aruco_align_result_callback:
            self.aruco_align_result_callback(robot_id, result.status)

    @_navigation_locked
    def _on_amcl_pose(self, robot_id: str, msg: PoseStamped) -> None:
        robot = fleet_manager.get_robot(robot_id)
        if robot is None:
            return

        x, y = msg.pose.position.x, msg.pose.position.y
        yaw = self._quaternion_to_yaw(msg.pose.orientation)
        if not all(math.isfinite(value) for value in (x, y, yaw)):
            # 잘못된 메시지로 정상 위치와 pose_received_at을 덮어쓰지 않는다.
            self._navigation_error(robot_id, "invalid_pose_message")
            return
        robot.update_pose(x=x, y=y, yaw=yaw)

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
