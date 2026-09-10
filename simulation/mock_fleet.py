import rclpy
from rclpy.node import Node
from geometry_msgs.msg import PoseStamped
import time
import math
import json
import zenoh

class FleetSimulatorNode(Node):
    def __init__(self):
        super().__init__('fleet_simulator_node')
        
        # 1. Zenoh 세션 초기화 (기존 인프라 7447 포트 연동)
        conf = zenoh.Config()
        # conf.insert_json5("connect/endpoints", '["tcp/127.0.0.1:7447"]')
        conf.insert_json5("connect/endpoints", '["tcp/10.10.141.15:7447"]')
        self.zenoh_session = zenoh.open(conf)
        self.get_logger().info("-> Zenoh 세션 연결 완료 (fms-zenoh-router:7447)")
        

        # 2. 관제 시스템에서 보내는 Goal 명령 구독 (robot1/goal 예시)
        self.zenoh_session.declare_subscriber("*/goal", self.on_zenoh_goal_received)

        # 3. ROS 2 퍼블리셔 선언 (필요시 내부 ROS 2 노드들과 통신용)
        self.goal_publishers = {
            "robot1": self.create_publisher(PoseStamped, '/robot1/goal_pose', 10),
            "robot2": self.create_publisher(PoseStamped, '/robot2/goal_pose', 10),
            "robot3": self.create_publisher(PoseStamped, '/robot3/goal_pose', 10),
        }

        # 4. 주기적 텔레메트리 발행을 위한 타이머 설정 (0.3초 주기)
        self.timer = self.create_timer(0.3, self.publish_telemetry_callback)
        self.angle = 0.0
        
        self.get_logger().info("-> 3대 로봇 군집 ROS 2 시뮬레이터 노드 구동 시작")

    def on_zenoh_goal_received(self, sample):
        """관제 웹에서 Zenoh로 보낸 주행 목표를 수신하여 ROS 2 토픽으로 전환"""
        try:
            topic = str(sample.key_expr)
            robot_id = topic.split('/')[0]
            payload = json.loads(sample.payload.to_bytes().decode('utf-8'))
            
            self.get_logger().info(f"[{robot_id}] Zenoh Goal 수신 -> X: {payload['x']}, Y: {payload['y']}")

            # ROS 2 PoseStamped 메시지로 변환 후 내부 발행
            if robot_id in self.goal_publishers:
                msg = PoseStamped()
                msg.header.stamp = self.get_clock().now().to_msg()
                msg.header.frame_id = 'map'
                msg.pose.position.x = float(payload['x'])
                msg.pose.position.y = float(payload['y'])
                msg.pose.orientation.w = 1.0
                self.goal_publishers[robot_id].publish(msg)
        except Exception as e:
            self.get_logger().error(f"Goal 처리 에러: {e}")

    def publish_telemetry_callback(self):
        """3대 로봇의 궤적을 계산하여 Zenoh 텔레메트리 토픽으로 발행"""
        robots = [
            {"id": "robot1", "r": 3.0, "spd": 0.05, "bat": 95.0, "status": "NAVIGATING"},
            {"id": "robot2", "r": 5.0, "spd": 0.03, "bat": 82.5, "status": "WORKING"},
            {"id": "robot3", "r": 1.5, "spd": 0.08, "bat": 45.0, "status": "RETURNING"}
        ]

        for r in robots:
            theta = self.angle * (r["spd"] / 0.05)
            x = r["r"] * math.cos(theta)
            y = r["r"] * math.sin(theta)
            
            payload = {
                "robot_id": r["id"],
                "x": round(x, 2),
                "y": round(y, 2),
                "yaw": round(theta + math.pi/2, 2),
                "battery": r["bat"],
                "status": r["status"]
            }
            
            # Zenoh를 통해 중앙 관제 서버로 위치 전송
            self.zenoh_session.put(f"{r['id']}/telemetry", json.dumps(payload).encode('utf-8'))

        self.angle += 0.05

    def destroy_node(self):
        self.zenoh_session.close()
        super().destroy_node()

def main(args=None):
    rclpy.init(args=args)
    node = FleetSimulatorNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        node.get_logger().info("군집 시뮬레이터 노드 종료 중...")
    finally:
        node.destroy_node()
        rclpy.shutdown()

if __name__ == '__main__':
    main()