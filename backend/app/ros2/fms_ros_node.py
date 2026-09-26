from __future__ import annotations

import rclpy as rp
from rclpy.node import Node

from geometry_msgs.msg import TwistStamped

from rclpy.qos import QoSProfile
from rclpy.timer import Timer
from rclpy.publisher import Publisher


class FmsRosNode(Node):
    def __init__(self):
        super().__init__("fms_node")
        self.get_logger().info("FMS Node initialized")
        # self.pub = self.creat_publisher(TwistStamped, "cmd_vel", QoSProfile(depth=10))
        # 연결되어 한 번이라도 등록된 로봇의 cmd_vel Publisher
        self._cmd_vel_publishers: dict[str, Publisher] = {}

    def register_robot(self, robot_id: str) -> None:

        # 이미 등록되어 있으면 새로 만들지 않음
        if robot_id in self._cmd_vel_publishers:
            return

        topic = f"/{robot_id}/cmd_vel"

        publisher = self.create_publisher(
            TwistStamped,
            topic,
            10,
        )

        self._cmd_vel_publishers[robot_id] = publisher

        self.get_logger().info(f"Robot registered: {robot_id} -> {topic}")

    def is_registered(self, robot_id: str) -> bool:

        return robot_id in self._cmd_vel_publishers

    def publish_cmd_vel(self, robot_id: str, linear_x: float, angular_z: float) -> None:

        publisher = self._cmd_vel_publishers.get(robot_id)

        if publisher is None:
            raise ValueError(f"Robot is not registered: {robot_id}")

        message = TwistStamped()

        message.header.stamp = self.get_clock().now().to_msg()

        message.twist.linear.x = float(linear_x)
        message.twist.angular.z = float(angular_z)

        publisher.publish(message)


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
