from __future__ import annotations

import rclpy as rp
from rclpy.node import Node
import math

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

        # 현재 실행 중인 FollowWaypoints Goal 관리
        self._follow_waypoints_goal_handles = {}

        self.navigation_result_callback = None
        self.precision_dock_result_callback = None

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
            PoseWithCovarianceStamped,
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

        # 딕셔너리에서 관리
        self._cmd_vel_publishers[robot_id] = publisher_cmd_vel
        self._pose_subscribers[robot_id] = subscription_pose
        self._battery_subscribers[robot_id] = subscription_battery
        self._follow_waypoints_clients[robot_id] = action_follow_waypoints_client
        self._precision_dock_clients[robot_id] = action_precision_dock_client

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

    def send_follow_waypoints_goal(
        self, robot_id: str, waypoints: list[tuple[float, float, float]]
    ) -> None:
        client = self._follow_waypoints_clients.get(robot_id)
        if client is None:
            raise ValueError(f"Robot is not registered: {robot_id}")

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
        future = client.send_goal_async(
            goal,
            feedback_callback=lambda feedback, rid=robot_id: self._on_follow_waypoints_feedback(
                rid, feedback
            ),
        )

        future.add_done_callback(
            lambda future, rid=robot_id: self._on_follow_waypoints_goal_response(rid, future)
        )

    def _on_follow_waypoints_goal_response(self, robot_id: str, future) -> None:
        goal_handle = future.result()

        if not goal_handle.accepted:
            self.get_logger().warning(f"FollowWaypoints goal rejected: {robot_id}")
            if self.navigation_result_callback:
                self.navigation_result_callback(robot_id, GoalStatus.STATUS_ABORTED)
            return
        # 현재 실행 중인 Goal 저장
        self._follow_waypoints_goal_handles[robot_id] = goal_handle

        self.get_logger().info(f"FollowWaypoints goal accepted: {robot_id}")

        result_future = goal_handle.get_result_async()

        result_future.add_done_callback(
            lambda future, rid=robot_id, handle=goal_handle: self._on_follow_waypoints_result(
                rid, handle, future
            )
        )

    def _on_follow_waypoints_result(self, robot_id: str, goal_handle, future) -> None:
        result = future.result()

        # 종료된 Goal이 현재 실행 중인 Goal일 때만 삭제
        current_handle = self._follow_waypoints_goal_handles.get(robot_id)

        if current_handle is goal_handle:
            self._follow_waypoints_goal_handles.pop(robot_id, None)
        else:
            return

        self.get_logger().info(f"FollowWaypoints finished: {robot_id}, " f"status={result.status}")

        if self.navigation_result_callback:
            self.navigation_result_callback(robot_id, result.status)

    def _on_follow_waypoints_feedback(self, robot_id: str, feedback_msg) -> None:
        feedback = feedback_msg.feedback

        self.get_logger().info(
            f"FollowWaypoints feedback: {robot_id}, "
            f"current_waypoint={feedback.current_waypoint}"
        )

    def cancel_follow_waypoints(self, robot_id: str, callback=None) -> None:
        goal_handle = self._follow_waypoints_goal_handles.get(robot_id)

        # 실행 중인 Goal이 없으면 바로 다음 작업
        if goal_handle is None:
            if callback:
                callback()
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
        response = future.result()

        if not response.goals_canceling:
            self.get_logger().warning(f"FollowWaypoints cancel failed: {robot_id}")
            return

        self.get_logger().info(f"FollowWaypoints cancel accepted: {robot_id}")

        current_handle = self._follow_waypoints_goal_handles.get(robot_id)

        if current_handle is goal_handle:
            self._follow_waypoints_goal_handles.pop(robot_id, None)

        if callback:
            callback()

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

    def _on_amcl_pose(self, robot_id: str, msg: PoseWithCovarianceStamped) -> None:
        robot = fleet_manager.get_robot(robot_id)
        if robot is None:
            return

        robot.update_pose(
            x=msg.pose.pose.position.x,
            y=msg.pose.pose.position.y,
            yaw=self._quaternion_to_yaw(msg.pose.pose.orientation),
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
