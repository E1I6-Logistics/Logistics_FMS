import rclpy
import json
import math
import time
from rclpy.node import Node
from std_msgs.msg import String

def main():
    rclpy.init()
    node = rclpy.create_node("robot_agent")

    # 상대 경로로 토픽 선언 (네임스페이스에 따라 자동 할당됨)
    telemetry_pub = node.create_publisher(String, "telemetry", 10)
    
    # 전역 변수
    current_x, current_y, current_yaw = 0.0, 0.0, 0.0
    target_x, target_y = None, None
    last_goal = None

    # [수신] 메인 PC -> 로봇 (목표 수신 콜백)
    def goal_cb(msg):
        nonlocal target_x, target_y, last_goal
        if msg.data != last_goal:
            last_goal = msg.data
            try:
                goal_data = json.loads(msg.data)
                target_x = float(goal_data.get("x", current_x))
                target_y = float(goal_data.get("y", current_y))
                node.get_logger().info(f"🎯 [명령 수신] 메인 PC가 새로운 목표를 지시함: ({target_x}, {target_y})")
            except Exception as e:
                node.get_logger().error(f"Goal 파싱 에러: {e}")

    goal_sub = node.create_subscription(String, "goal", goal_cb, 10)

    # 네임스페이스를 통해 본인의 ID 파악
    namespace = node.get_namespace()
    robot_id = namespace.strip("/")
    if not robot_id:
        robot_id = "unknown"

    node.get_logger().info(f"🚀 [{robot_id}] 1:3 양방향 통신 테스트 에이전트 가동")

    # 로봇별 초기 시작 위치 다르게 설정 (겹침 방지)
    if robot_id == "robot1":
        current_x, current_y, current_yaw = 1.0, 1.0, 0.0
    elif robot_id == "robot2":
        current_x, current_y, current_yaw = 2.0, -1.0, 0.5
    elif robot_id == "robot3":
        current_x, current_y, current_yaw = -1.0, 2.0, 1.0
        
    target_x, target_y = current_x, current_y
    battery = 100.0

    try:
        while rclpy.ok():
            # 1. 목표지점을 향해 부드럽게 이동하는 수학적 시뮬레이션
            dx = target_x - current_x
            dy = target_y - current_y
            dist = math.hypot(dx, dy)

            if dist > 0.1:
                # 이동 중 (1주기에 0.1m 씩 전진)
                current_x += (dx / dist) * 0.1
                current_y += (dy / dist) * 0.1
                current_yaw = math.atan2(dy, dx)
                status = "MOVING"
                battery -= 0.05
            else:
                # 도착 완료 후 대기
                current_x, current_y = target_x, target_y
                status = "IDLE"
                battery -= 0.01
                
            battery = max(10.0, battery)

            # 2. [송신] 로봇 -> 메인 PC (주기적 상태 보고)
            payload = {
                "robot_id": robot_id,
                "x": round(current_x, 3),
                "y": round(current_y, 3),
                "yaw": round(current_yaw, 3),
                "battery": round(battery, 1),
                "status": status
            }

            msg = String()
            msg.data = json.dumps(payload)
            telemetry_pub.publish(msg)

            node.get_logger().info(f"📡 [주기적 송신] 메인 PC로 상태 보고 -> 위치:({payload['x']}, {payload['y']}) 상태:{status}")

            # 콜백 처리 및 1초 대기 (1Hz 통신)
            rclpy.spin_once(node, timeout_sec=0.1)
            time.sleep(0.9)

    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()

if __name__ == "__main__":
    main()
