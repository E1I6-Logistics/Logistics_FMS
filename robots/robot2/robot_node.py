import rclpy
from rclpy.node import Node
from std_msgs.msg import String
import json
import math

class RobotNode(Node):
    def __init__(self):
        super().__init__('robot2_core_node')

        # 1. 텔레메트리 퍼블리셔
        self.telemetry_pub = self.create_publisher(String, '/robot2/telemetry', 10)

        # 2. 관제 화면에서 보낸 주행 목표를 수신할 String 서브스크라이버
        self.goal_sub = self.create_subscription(
            String,
            '/robot2/goal',
            self.on_goal_received,
            10
        )

        # 3. 주행 모의 타이머
        self.timer = self.create_timer(0.3, self.publish_telemetry)
        self.angle = 0.0
        self.battery = 98.0
        self.get_logger().info("-> [Robot2] 순수 ROS 2 노드 기동 완료")

    def publish_telemetry(self):
        x = 3.0 * math.cos(self.angle)
        y = 3.0 * math.sin(self.angle)
        yaw = self.angle + (math.pi / 2.0)
        self.battery = max(10.0, self.battery - 0.01)

        payload = {
            "robot_id": "robot2",
            "x": round(x, 2),
            "y": round(y, 2),
            "yaw": round(yaw, 2),
            "battery": round(self.battery, 1),
            "status": "NAVIGATING"
        }

        msg = String()
        msg.data = json.dumps(payload)
        self.telemetry_pub.publish(msg)

        self.angle += 0.05

    def on_goal_received(self, msg: String):
        try:
            # 수신된 JSON 파싱
            payload = json.loads(msg.data)
            self.get_logger().info(
                f"-> [Robot2] 주행 목표 수신 성공! Target X: {payload.get('x')}, Target Y: {payload.get('y')}"
            )
        except Exception as e:
            self.get_logger().error(f"Goal 수신 데이터 파싱 에러: {e}")

def main(args=None):
    rclpy.init(args=args)
    node = RobotNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()

if __name__ == '__main__':
    main()