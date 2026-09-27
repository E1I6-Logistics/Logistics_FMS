from __future__ import annotations

import rclpy as rp
from rclpy.node import Node
import math

from rclpy.publisher import Publisher
from rclpy.subscription import Subscription
from rclpy.action import ActionClient


from geometry_msgs.msg import Quaternion
from geometry_msgs.msg import TwistStamped
from geometry_msgs.msg import PoseWithCovarianceStamped
from sensor_msgs.msg import BatteryState
from nav2_msgs.action import FollowWaypoints

from ..services.fleet_manager import fleet_manager


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

    def register_robot(self, robot_id: str) -> None:

        # 이미 등록되어 있으면 새로 만들지 않음
        if robot_id in self._registered_robots:
            return

        # 발행
        publisher_cmd_vel = self.create_publisher(TwistStamped, f"/{robot_id}/cmd_vel", 10)

        # 구독
        subscription_pose = self.create_subscription(
            PoseWithCovarianceStamped,
            f"/{robot_id}/amcl_pose",
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

        # 딕셔너리에서 관리
        self._cmd_vel_publishers[robot_id] = publisher_cmd_vel
        self._pose_subscribers[robot_id] = subscription_pose
        self._battery_subscribers[robot_id] = subscription_battery
        self._follow_waypoints_clients[robot_id] = action_follow_waypoints_client

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
