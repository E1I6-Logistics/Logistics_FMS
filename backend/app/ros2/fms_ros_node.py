from __future__ import annotations

import rclpy as rp
from rclpy.node import Node
import math
from functools import wraps
from threading import RLock
from time import monotonic, strftime

from rclpy.publisher import Publisher
from rclpy.subscription import Subscription
from rclpy.action import ActionClient

from geometry_msgs.msg import Quaternion
from geometry_msgs.msg import TwistStamped
from geometry_msgs.msg import PoseStamped
from geometry_msgs.msg import PoseWithCovarianceStamped
from nav2_msgs.action import NavigateThroughPoses

from ..services.fleet_manager import fleet_manager

from action_msgs.msg import GoalStatus
from sensor_msgs.msg import BatteryState
from turtlebot3_my_msg.action import PrecisionDock
from logitle_aruco_msgs.action import AlignAndCorrectWithAruco
from ..config import REAL_CANCEL_TIMEOUT_S

RESULT_QUERY_LIMIT = 3


def _navigation_locked(method):
    @wraps(method)
    def locked(self, *args, **kwargs):
        with self.navigation_lock:
            return method(self, *args, **kwargs)

    return locked


class FmsRosNode(Node):
    def __init__(self):
        super().__init__("fms_node")
        print(f"[{strftime('%Y-%m-%d %H:%M:%S')}] [INFO] [ROS NODE] FMS Node initialized", flush=True)

        self._registered_robots: set[str] = set()

        # 연결되어 한 번이라도 등록된 로봇의 Publisher, Subscription, ActionClient를 관리
        self._cmd_vel_publishers: dict[str, Publisher] = {}

        self._battery_subscribers: dict[str, Subscription] = {}
        self._pose_subscribers: dict[str, Subscription] = {}

        self._follow_waypoints_clients: dict[str, ActionClient] = {}
        self._precision_dock_clients: dict[str, ActionClient] = {}
        self._aruco_align_clients: dict[str, ActionClient] = {}

        # 현재 실행 중인 NavigateThroughPoses Goal 관리
        self._follow_waypoints_goal_handles = {}
        # Goal 수락 대기 중에도 취소 요청을 기억한다. 콜백은 terminal result 뒤 실행
        self._follow_waypoints_pending = set()
        self._follow_waypoints_cancel_callbacks = {}
        self._follow_waypoints_feedback_tokens = {}
        self._follow_waypoints_feedback_last = {}
        self._result_query_at = {}
        self._result_query_count = {}
        # 도킹/ArUco도 종료 Result를 확인할 때까지 새 작업을 시작하지 않는다.
        self._auxiliary_goals = {}
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
            self, NavigateThroughPoses, f"/{robot_id}/navigate_through_poses"
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
        print(
            f"[{strftime('%Y-%m-%d %H:%M:%S')}] [INFO] [ROS ACTION READY] robot={robot_id} "
            f"navigate_through_poses={action_follow_waypoints_client.server_is_ready()}",
            flush=True,
        )
        # 모든 인터페이스 생성이 끝난 후 등록 처리
        self._registered_robots.add(robot_id)
        print(f"[{strftime('%Y-%m-%d %H:%M:%S')}] [INFO] [ROS NODE] Robot registered: {robot_id}", flush=True)

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
        if not waypoints:
            raise ValueError(f"NavigateThroughPoses 경유점이 비어 있습니다: {robot_id}")
        client = self._follow_waypoints_clients.get(robot_id)
        if client is None:
            raise ValueError(f"Robot is not registered: {robot_id}")

        if (
            robot_id in self._follow_waypoints_pending
            or robot_id in self._follow_waypoints_goal_handles
        ):
            raise RuntimeError(f"이전 NavigateThroughPoses 실행이 종료되지 않았습니다: {robot_id}")
        print(
            f"[{strftime('%Y-%m-%d %H:%M:%S')}] [INFO] [ROS NAV CHECK] robot={robot_id} " f"ready={client.server_is_ready()}",
            flush=True,
        )
        # Nav2 NavigateThroughPoses Action Server 연결 확인
        if not client.wait_for_server(timeout_sec=5.0):
            raise RuntimeError(f"NavigateThroughPoses Action Server를 찾을 수 없습니다: {robot_id}")

        # NavigateThroughPoses Goal 생성
        goal = NavigateThroughPoses.Goal()
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
        print(
            f"[{strftime('%Y-%m-%d %H:%M:%S')}] [INFO] [ROS NAV GOAL] robot={robot_id} "
            f"pose_count={len(poses)} last=({waypoints[-1][0]:.3f}, {waypoints[-1][1]:.3f})",
            flush=True,
        )

        # 비동기로 Goal 전송
        token = (object(), len(poses))
        self._follow_waypoints_feedback_tokens[robot_id] = token
        self._follow_waypoints_feedback_last.pop(robot_id, None)
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
        print(
            f"[{strftime('%Y-%m-%d %H:%M:%S')}] [ERROR] [ROS NAV ERROR] robot={robot_id} reason={reason}", flush=True
        )
        if getattr(self, "navigation_error_callback", None):
            self.navigation_error_callback(robot_id, reason)

    @_navigation_locked
    def _on_follow_waypoints_goal_response(self, robot_id: str, future) -> None:
        try:
            goal_handle = future.result()
        except Exception as exc:
            # 서버가 수락했는지 알 수 없으므로 pending을 지우고 새 Goal을 보내면 안 된다.
            self._navigation_error(
                robot_id, f"goal_response_error:{type(exc).__name__}:{exc}"
            )
            return
        self._follow_waypoints_pending.discard(robot_id)

        if not goal_handle.accepted:
            self._follow_waypoints_feedback_tokens.pop(robot_id, None)
            self._follow_waypoints_feedback_last.pop(robot_id, None)
            callback = self._follow_waypoints_cancel_callbacks.pop(robot_id, None)
            if callback is not None:
                callback()
                return
            print(f"[{strftime('%Y-%m-%d %H:%M:%S')}] [WARN] [ROS NAV] goal rejected: robot={robot_id}", flush=True)
            if self.navigation_result_callback:
                self.navigation_result_callback(robot_id, GoalStatus.STATUS_ABORTED)
            return

        # 현재 실행 중인 Goal 저장
        self._follow_waypoints_goal_handles[robot_id] = goal_handle

        print(f"[{strftime('%Y-%m-%d %H:%M:%S')}] [INFO] [ROS NAV] goal accepted: robot={robot_id}", flush=True)

        self._query_navigation_result(robot_id, goal_handle)
        if robot_id in self._follow_waypoints_cancel_callbacks:
            self.cancel_follow_waypoints(
                robot_id, self._follow_waypoints_cancel_callbacks[robot_id]
            )

    def _query_navigation_result(self, robot_id: str, goal_handle) -> None:
        self._result_query_at[robot_id] = monotonic()
        self._result_query_count[robot_id] = self._result_query_count.get(robot_id, 0) + 1
        attempt = self._result_query_count[robot_id]
        try:
            future = goal_handle.get_result_async()

            def on_result(result_future):
                self._on_follow_waypoints_result(robot_id, goal_handle, result_future)

            future.add_done_callback(on_result)
            print(
                f"[{strftime('%Y-%m-%d %H:%M:%S')}] [INFO] [ROS NAV RESULT] "
                f"robot={robot_id} 결과 확인 요청 attempt={attempt}",
                flush=True,
            )
        except Exception as exc:
            self._navigation_error(
                robot_id, f"result_subscription_error:{type(exc).__name__}:{exc}"
            )

    @_navigation_locked
    def reconcile_navigation_results(self) -> None:
        """취소 중 결과 응답이 유실되면 재조회한다. 종료 전 Goal은 유지한다."""
        now = monotonic()
        # 결과 알림이 오는 동안 목록이 바뀔 수 있으므로 현재 목록을 복사해 순회한다.
        for rid, handle in list(self._follow_waypoints_goal_handles.items()):
            if rid not in self._follow_waypoints_cancel_callbacks:
                continue
            if self._result_query_count.get(rid, 0) >= RESULT_QUERY_LIMIT:
                continue
            if now - self._result_query_at.get(rid, now) >= REAL_CANCEL_TIMEOUT_S:
                self._query_navigation_result(rid, handle)

    @_navigation_locked
    def _on_follow_waypoints_result(self, robot_id: str, goal_handle, future) -> None:
        # 이전 Goal의 Future가 실패했어도 현재 Goal에는 영향을 주지 않는다.
        if self._follow_waypoints_goal_handles.get(robot_id) is not goal_handle:
            return
        try:
            result = future.result()
        except Exception as exc:
            self._navigation_error(robot_id, f"result_error:{type(exc).__name__}:{exc}")
            return
        self._follow_waypoints_goal_handles.pop(robot_id, None)
        self._result_query_at.pop(robot_id, None)
        self._result_query_count.pop(robot_id, None)
        self._follow_waypoints_feedback_tokens.pop(robot_id, None)
        self._follow_waypoints_feedback_last.pop(robot_id, None)

        detail = getattr(result, "result", None)
        if result.status == GoalStatus.STATUS_SUCCEEDED:
            level = "INFO"
        elif result.status == GoalStatus.STATUS_CANCELED:
            level = "WARN"
        else:
            level = "ERROR"
        print(
            f"[{strftime('%Y-%m-%d %H:%M:%S')}] [{level}] [ROS NAV] robot={robot_id} "
            f"최종 결과 status={result.status} error_code={getattr(detail, 'error_code', None)} "
            f"error_msg={getattr(detail, 'error_msg', None)!r}",
            flush=True,
        )

        callback = self._follow_waypoints_cancel_callbacks.pop(robot_id, None)
        if callback is not None:
            callback()
        elif self.navigation_result_callback:
            self.navigation_result_callback(robot_id, result.status)

    @_navigation_locked
    def _on_follow_waypoints_feedback(self, robot_id: str, feedback_msg, token=None) -> None:
        current_token = self._follow_waypoints_feedback_tokens.get(robot_id)
        if token is not None and current_token is not token:
            return  # 이전 Goal의 늦은 Feedback은 새 경로 인덱스를 바꾸지 않는다.
        if current_token is None:
            return
        feedback = feedback_msg.feedback
        count = current_token[1]
        current_waypoint = max(0, min(count - 1, count - feedback.number_of_poses_remaining))

        reported = (count, feedback.number_of_poses_remaining)
        if self._follow_waypoints_feedback_last.get(robot_id) != reported:
            self._follow_waypoints_feedback_last[robot_id] = reported
            print(
                f"[{strftime('%Y-%m-%d %H:%M:%S')}] [INFO] [ROS NAV FEEDBACK] robot={robot_id} "
                f"current_waypoint={current_waypoint} sent={count} "
                f"remaining={feedback.number_of_poses_remaining}",
                flush=True,
            )
        # 점유 확정은 Pose에서만 한다. Feedback은 현재 Goal의 진행 순서만 전달한다.
        if getattr(self, "navigation_feedback_callback", None):
            self.navigation_feedback_callback(robot_id, current_waypoint)

    @_navigation_locked
    def cancel_follow_waypoints(self, robot_id: str, callback=None) -> None:
        callback = callback or (lambda: None)
        self._follow_waypoints_cancel_callbacks[robot_id] = callback
        if robot_id in self._follow_waypoints_pending:
            print(
                f"[{strftime('%Y-%m-%d %H:%M:%S')}] [INFO] [ROS NAV CANCEL] waiting for goal response: "
                f"robot={robot_id}",
                flush=True,
            )
            return
        goal_handle = self._follow_waypoints_goal_handles.get(robot_id)

        # 실행 중인 Goal이 없으면 바로 다음 작업
        if goal_handle is None:
            self._follow_waypoints_cancel_callbacks.pop(robot_id, None)
            callback()
            return

        print(f"[{strftime('%Y-%m-%d %H:%M:%S')}] [INFO] [ROS NAV CANCEL] requested: robot={robot_id}", flush=True)

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

        print(f"[{strftime('%Y-%m-%d %H:%M:%S')}] [INFO] [ROS NAV CANCEL] accepted: robot={robot_id}", flush=True)

        # 취소 수락은 실행 종료가 아니다. handle과 예약은 result 수신까지 유지한다.

    @_navigation_locked
    def has_active_auxiliary(self, robot_id: str) -> bool:
        return robot_id in self._auxiliary_goals

    @_navigation_locked
    def cancel_auxiliary(self, robot_id: str, callback=None) -> None:
        callback = callback or (lambda: None)
        entry = self._auxiliary_goals.get(robot_id)
        if entry is None:
            callback()
            return
        entry["cancel_callback"] = callback
        if entry["handle"] is not None and not entry["cancel_sent"]:
            self._send_auxiliary_cancel(robot_id, entry)

    def _send_auxiliary_cancel(self, robot_id, entry):
        entry["cancel_sent"] = True
        try:
            future = entry["handle"].cancel_goal_async()
            future.add_done_callback(
                lambda future, rid=robot_id, expected=entry: self._on_auxiliary_cancel(
                    rid, expected, future
                )
            )
            print(
                f"[{strftime('%Y-%m-%d %H:%M:%S')}] [INFO] [ROS AUX CANCEL] robot={robot_id} "
                f"action={entry['kind']} requested",
                flush=True,
            )
        except Exception as exc:
            entry["cancel_sent"] = False
            print(
                f"[{strftime('%Y-%m-%d %H:%M:%S')}] [ERROR] [ROS AUX ERROR] robot={robot_id} "
                f"action={entry['kind']} cancel_send_failed={exc!r}",
                flush=True,
            )

    @_navigation_locked
    def _on_auxiliary_cancel(self, robot_id, entry, future):
        if self._auxiliary_goals.get(robot_id) is not entry:
            return
        try:
            accepted = bool(future.result().goals_canceling)
        except Exception as exc:
            accepted = False
            print(
                f"[{strftime('%Y-%m-%d %H:%M:%S')}] [ERROR] [ROS AUX ERROR] robot={robot_id} "
                f"action={entry['kind']} cancel_response_failed={exc!r}",
                flush=True,
            )
        if not accepted:
            print(
                f"[{strftime('%Y-%m-%d %H:%M:%S')}] [ERROR] [ROS AUX ERROR] robot={robot_id} "
                f"action={entry['kind']} cancel rejected",
                flush=True,
            )
            return
        print(
            f"[{strftime('%Y-%m-%d %H:%M:%S')}] [INFO] [ROS AUX CANCEL] robot={robot_id} "
            f"action={entry['kind']} accepted; waiting for terminal result",
            flush=True,
        )

    def _finish_auxiliary(self, robot_id, entry, status, result_callback):
        if self._auxiliary_goals.get(robot_id) is not entry:
            return
        self._auxiliary_goals.pop(robot_id, None)
        callback = entry["cancel_callback"]
        if callback is not None:
            print(
                f"[{strftime('%Y-%m-%d %H:%M:%S')}] [INFO] [ROS AUX CANCEL] robot={robot_id} "
                f"action={entry['kind']} confirmed terminal status={status}",
                flush=True,
            )
            callback()
        elif result_callback:
            result_callback(robot_id, status)

    @_navigation_locked
    def send_precision_dock(self, robot_id):
        if robot_id in self._auxiliary_goals:
            raise RuntimeError(f"이전 보조 Action이 종료되지 않았습니다: {robot_id}")
        client = self._precision_dock_clients.get(robot_id)

        if client is None:
            print(
                f"[{strftime('%Y-%m-%d %H:%M:%S')}] [ERROR] [ROS DOCK ERROR] robot={robot_id} client not available",
                flush=True,
            )
            raise ValueError(f"PrecisionDock client not found: {robot_id}")

        print(
            f"[{strftime('%Y-%m-%d %H:%M:%S')}] [INFO] [ROS NAV CHECK] robot={robot_id} " f"ready={client.server_is_ready()}",
            flush=True,
        )
        if not client.wait_for_server(timeout_sec=5.0):
            print(
                f"[{strftime('%Y-%m-%d %H:%M:%S')}] [ERROR] [ROS DOCK ERROR] robot={robot_id} server not available",
                flush=True,
            )
            if self.precision_dock_result_callback:
                self.precision_dock_result_callback(robot_id, GoalStatus.STATUS_ABORTED)

            return

        goal = PrecisionDock.Goal()

        goal.target_pose.header.frame_id = "base_link"
        goal.target_pose.pose.position.x = 0.0
        goal.target_pose.pose.position.y = 0.0
        goal.target_pose.pose.position.z = 0.0
        goal.target_pose.pose.orientation.w = 1.0

        entry = {
            "kind": "PrecisionDock",
            "handle": None,
            "cancel_callback": None,
            "cancel_sent": False,
        }
        self._auxiliary_goals[robot_id] = entry
        try:
            future = client.send_goal_async(goal)
        except Exception:
            self._auxiliary_goals.pop(robot_id, None)
            raise
        future.add_done_callback(
            lambda future, expected=entry: self._on_precision_dock_goal_response(
                robot_id, future, expected
            )
        )

    @_navigation_locked
    def _on_precision_dock_goal_response(self, robot_id: str, future, entry=None) -> None:
        entry = entry or self._auxiliary_goals.get(robot_id)
        if self._auxiliary_goals.get(robot_id) is not entry:
            return
        try:
            goal_handle = future.result()
        except Exception as exc:
            print(
                f"[{strftime('%Y-%m-%d %H:%M:%S')}] [ERROR] [ROS DOCK ERROR] robot={robot_id} "
                f"goal response failed={exc!r}",
                flush=True,
            )
            self._finish_auxiliary(
                robot_id, entry, GoalStatus.STATUS_ABORTED, self.precision_dock_result_callback
            )
            return

        if not goal_handle.accepted:
            print(
                f"[{strftime('%Y-%m-%d %H:%M:%S')}] [ERROR] [ROS DOCK ERROR] robot={robot_id} goal rejected",
                flush=True,
            )

            self._finish_auxiliary(
                robot_id, entry, GoalStatus.STATUS_ABORTED, self.precision_dock_result_callback
            )
            return

        entry["handle"] = goal_handle
        print(f"[{strftime('%Y-%m-%d %H:%M:%S')}] [INFO] [ROS DOCK] robot={robot_id} goal accepted", flush=True)

        try:
            result_future = goal_handle.get_result_async()
        except Exception as exc:
            print(
                f"[{strftime('%Y-%m-%d %H:%M:%S')}] [ERROR] [ROS DOCK ERROR] robot={robot_id} "
                f"result subscription failed={exc!r}",
                flush=True,
            )
            return

        result_future.add_done_callback(
            lambda future, rid=robot_id, expected=entry: self._on_precision_dock_result(
                rid, future, expected
            )
        )
        if entry["cancel_callback"] is not None:
            self._send_auxiliary_cancel(robot_id, entry)

    @_navigation_locked
    def _on_precision_dock_result(self, robot_id: str, future, entry=None) -> None:
        entry = entry or self._auxiliary_goals.get(robot_id)
        if self._auxiliary_goals.get(robot_id) is not entry:
            return
        try:
            result = future.result()
        except Exception as exc:
            print(
                f"[{strftime('%Y-%m-%d %H:%M:%S')}] [ERROR] [ROS DOCK ERROR] robot={robot_id} "
                f"result failed={exc!r}",
                flush=True,
            )
            return

        print(
            f"[{strftime('%Y-%m-%d %H:%M:%S')}] [INFO] [ROS DOCK] robot={robot_id} "
            f"finished status={result.status}",
            flush=True,
        )

        self._finish_auxiliary(robot_id, entry, result.status, self.precision_dock_result_callback)

    @_navigation_locked
    def send_aruco_align(self, robot_id: str, marker_id: int) -> None:
        if robot_id in self._auxiliary_goals:
            raise RuntimeError(f"이전 보조 Action이 종료되지 않았습니다: {robot_id}")
        client = self._aruco_align_clients.get(robot_id)

        if client is None:
            raise ValueError(f"Aruco Align Action client를 찾을 수 없습니다: {robot_id}")
        print(
            f"[{strftime('%Y-%m-%d %H:%M:%S')}] [INFO] [ROS NAV CHECK] robot={robot_id} " f"ready={client.server_is_ready()}",
            flush=True,
        )
        # Action Server 연결 확인
        if not client.wait_for_server(timeout_sec=5.0):
            print(
                f"[{strftime('%Y-%m-%d %H:%M:%S')}] [ERROR] [ROS ARUCO ERROR] robot={robot_id} "
                "Action Server를 찾을 수 없습니다.",
                flush=True,
            )

            if self.aruco_align_result_callback:
                self.aruco_align_result_callback(robot_id, GoalStatus.STATUS_ABORTED)

            return

        # Goal 생성
        goal = AlignAndCorrectWithAruco.Goal()
        goal.marker_id = int(marker_id)
        goal.apply_correction = True

        print(
            f"[{strftime('%Y-%m-%d %H:%M:%S')}] [INFO] [ROS ARUCO] Goal 전송: "
            f"robot={robot_id}, marker_id={marker_id}",
            flush=True,
        )

        # Feedback callback은 사용하지 않음
        entry = {"kind": "ArUco", "handle": None, "cancel_callback": None, "cancel_sent": False}
        self._auxiliary_goals[robot_id] = entry
        try:
            future = client.send_goal_async(goal)
        except Exception:
            self._auxiliary_goals.pop(robot_id, None)
            raise
        future.add_done_callback(
            lambda future, rid=robot_id, expected=entry: self._on_aruco_align_goal_response(
                rid, future, expected
            )
        )

    @_navigation_locked
    def _on_aruco_align_goal_response(self, robot_id: str, future, entry=None) -> None:
        entry = entry or self._auxiliary_goals.get(robot_id)
        if self._auxiliary_goals.get(robot_id) is not entry:
            return
        try:
            goal_handle = future.result()
        except Exception as exc:
            print(
                f"[{strftime('%Y-%m-%d %H:%M:%S')}] [ERROR] [ROS ARUCO ERROR] robot={robot_id} "
                f"goal response failed={exc!r}",
                flush=True,
            )
            self._finish_auxiliary(
                robot_id, entry, GoalStatus.STATUS_ABORTED, self.aruco_align_result_callback
            )
            return

        if not goal_handle.accepted:
            print(f"[{strftime('%Y-%m-%d %H:%M:%S')}] [WARN] [ROS ARUCO] Goal 거부: {robot_id}", flush=True)

            self._finish_auxiliary(
                robot_id, entry, GoalStatus.STATUS_ABORTED, self.aruco_align_result_callback
            )

            return

        entry["handle"] = goal_handle
        print(f"[{strftime('%Y-%m-%d %H:%M:%S')}] [INFO] [ROS ARUCO] Goal 수락: {robot_id}", flush=True)

        try:
            result_future = goal_handle.get_result_async()
        except Exception as exc:
            print(
                f"[{strftime('%Y-%m-%d %H:%M:%S')}] [ERROR] [ROS ARUCO ERROR] robot={robot_id} "
                f"result subscription failed={exc!r}",
                flush=True,
            )
            return

        result_future.add_done_callback(
            lambda future, rid=robot_id, expected=entry: self._on_aruco_align_result(
                rid, future, expected
            )
        )
        if entry["cancel_callback"] is not None:
            self._send_auxiliary_cancel(robot_id, entry)

    @_navigation_locked
    def _on_aruco_align_result(self, robot_id: str, future, entry=None) -> None:
        entry = entry or self._auxiliary_goals.get(robot_id)
        if self._auxiliary_goals.get(robot_id) is not entry:
            return
        try:
            result = future.result()
        except Exception as exc:
            print(
                f"[{strftime('%Y-%m-%d %H:%M:%S')}] [ERROR] [ROS ARUCO ERROR] robot={robot_id} "
                f"result failed={exc!r}",
                flush=True,
            )
            return
        print(
            f"[{strftime('%Y-%m-%d %H:%M:%S')}] [INFO] [ROS ARUCO] 완료: "
            f"robot={robot_id}, status={result.status}",
            flush=True,
        )

        self._finish_auxiliary(robot_id, entry, result.status, self.aruco_align_result_callback)

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
