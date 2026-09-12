# ROS 2 파이썬 클라이언트 라이브러리(rclpy)와 데이터 직렬화를 위한 json, 수학 계산을 위한 math 등을 불러옵니다.
import rclpy
import json
import math
import time
from rclpy.node import Node
from std_msgs.msg import String

def main():
    # ROS 2 통신 시스템을 초기화하고, "robot_agent"라는 이름의 노드를 생성합니다.
    rclpy.init()
    node = rclpy.create_node("robot_agent")

    # 상대 경로로 토픽 선언 (네임스페이스에 따라 자동 할당됨)
    # 자신의 상태를 외부에 알리기 위한 발행자(Publisher)를 생성합니다. 
    # 토픽 이름이 "telemetry"이므로, Launch 파일의 Zenoh 브릿지를 거치면 외부에서는 "/robot1/telemetry"로 보이게 됩니다.
    telemetry_pub = node.create_publisher(String, "telemetry", 10)
    
    # 전역 변수
    # 로봇의 현재 위치(x, y), 바라보는 방향(yaw), 목표 위치(target) 등을 저장할 변수들을 초기화합니다.
    current_x, current_y, current_yaw = 0.0, 0.0, 0.0
    target_x, target_y, last_goal = None, None, None

    # [수신] 메인 PC -> 로봇 (목표 수신 콜백)
    # 메인 PC에서 "goal" 토픽으로 메시지가 들어올 때마다 자동으로 실행되는 함수(콜백)입니다.
    def goal_cb(msg):
        # 함수 내부에서 바깥쪽에 있는 전역 변수들을 수정하기 위해 nonlocal 키워드를 사용합니다.
        nonlocal target_x, target_y, last_goal
        
        # 중복된 목표 명령이 아닐 경우에만 처리합니다.
        if msg.data != last_goal:
            last_goal = msg.data
            try:
                # 수신된 JSON 형태의 문자열(msg.data)을 파이썬 딕셔너리로 변환하여 목표 x, y 좌표를 추출합니다.
                goal_data = json.loads(msg.data)
                target_x = float(goal_data.get("x", current_x))
                target_y = float(goal_data.get("y", current_y))
                node.get_logger().info(f"🎯 [명령 수신] 메인 PC가 새로운 목표를 지시함: ({target_x}, {target_y})")
            except Exception as e:
                # JSON 파싱에 실패하거나 데이터가 잘못되었을 경우 에러 로그를 출력합니다.
                node.get_logger().error(f"Goal 파싱 에러: {e}")

    # "goal" 토픽을 구독(Subscribe)하도록 설정하며, 메시지가 들어오면 위에서 정의한 goal_cb 함수를 호출하도록 연결합니다.
    goal_sub = node.create_subscription(String, "goal", goal_cb, 10)

    # 네임스페이스를 통해 본인의 ID 파악
    # Launch 파일에서 전달해 준 'robot_id' 파라미터를 읽어옵니다. 이를 통해 자신이 1번 로봇인지 2번 로봇인지 인지합니다.
    node.declare_parameter('robot_id', 'unknown_robot')
    robot_id = node.get_parameter('robot_id').value
    if not robot_id:
        robot_id = "unknown"

    node.get_logger().info(f"🚀 [{robot_id}] 1:3 양방향 통신 테스트 에이전트 가동")

    # 로봇별 초기 시작 위치 다르게 설정 (겹침 방지)
    # 테스트 환경에서 여러 로봇이 겹쳐서 시작하는 것을 막기 위해, 부여받은 ID에 따라 초기 시작 x, y 좌표와 바라보는 방향(yaw)을 하드코딩으로 분기하여 설정합니다.
    if robot_id == "robot1":
        current_x, current_y, current_yaw = 1.0, 1.0, 0.0
    elif robot_id == "robot2":
        current_x, current_y, current_yaw = 2.0, -1.0, 0.5
    elif robot_id == "robot3":
        current_x, current_y, current_yaw = -1.0, 2.0, 1.0
        
    target_x, target_y = current_x, current_y
    battery = 100.0

    try:
        # rclpy.ok()는 ROS 2 시스템이 정상적으로 켜져 있는 동안 계속 True를 반환하므로, 프로그램 종료 전까지 무한 루프를 돕니다.
        while rclpy.ok():
            # 1. 목표지점을 향해 부드럽게 이동하는 수학적 시뮬레이션
            # 목표 위치와 현재 위치의 차이(dx, dy)를 구하고, 피타고라스의 정리(math.hypot)를 이용해 남은 직선 거리(dist)를 계산합니다.
            dx = target_x - current_x
            dy = target_y - current_y
            dist = math.hypot(dx, dy)

            if dist > 0.1:
                # 이동 중 (1주기에 0.1m 씩 전진)
                # 남은 거리가 0.1 이상이면 아직 도착하지 않은 것으로 간주하고, x축과 y축 방향 비율(dx/dist, dy/dist)에 맞게 0.1m씩 좌표를 갱신합니다.
                current_x += (dx / dist) * 0.1
                current_y += (dy / dist) * 0.1
                # math.atan2 함수를 사용해 목표 지점을 바라보도록 로봇의 각도(yaw)를 자연스럽게 회전시킵니다.
                current_yaw = math.atan2(dy, dx)
                status = "MOVING"
                battery -= 0.05 # 이동 중이므로 배터리를 많이 소모합니다.
            else:
                # 도착 완료 후 대기
                # 목표 지점에 거의 도달했다면(0.1 이하) 좌표를 목표지점과 완전히 맞추고 대기 상태(IDLE)로 전환합니다.
                current_x, current_y = target_x, target_y
                status = "IDLE"
                battery -= 0.01 # 대기 중이므로 배터리를 적게 소모합니다.
                
            # 배터리가 10% 밑으로 떨어지지 않게 하한선을 설정합니다. (방전 방지)
            battery = max(10.0, battery)

            # 2. [송신] 로봇 -> 메인 PC (주기적 상태 보고)
            # 계산된 최신 위치, 각도, 배터리 잔량, 현재 상태(MOVING/IDLE)를 딕셔너리 형태로 묶습니다.
            payload = {
                "robot_id": robot_id,
                "x": round(current_x, 3), # 소수점 3자리까지만 표시하여 데이터 크기를 최적화합니다.
                "y": round(current_y, 3),
                "yaw": round(current_yaw, 3),
                "battery": round(battery, 1),
                "status": status
            }

            # 딕셔너리를 JSON 문자열로 변환(json.dumps)한 뒤, String 메시지에 담아 "telemetry" 토픽으로 발행합니다.
            msg = String()
            msg.data = json.dumps(payload)
            telemetry_pub.publish(msg)

            node.get_logger().info(f"📡 [주기적 송신] 메인 PC로 상태 보고 -> 위치:({payload['x']}, {payload['y']}) 상태:{status}")

            # 콜백 처리 및 1초 대기 (1Hz 통신)
            # 메인 PC로부터 들어온 'goal' 메시지가 있는지 확인하고 콜백 함수(goal_cb)를 실행할 기회를 0.1초 동안 줍니다.
            rclpy.spin_once(node, timeout_sec=0.1)
            # 그 후 0.9초를 쉬어서 전체 루프가 대략 1초에 한 번(1Hz)씩 돌도록 조절합니다.
            time.sleep(0.9)

    except KeyboardInterrupt:
        # 사용자가 터미널에서 Ctrl+C를 누르면 발생하는 예외를 처리하여 에러 없이 부드럽게 종료되도록 합니다.
        pass
    finally:
        # 프로그램이 종료될 때 노드를 메모리에서 해제하고 ROS 2 통신을 안전하게 닫습니다.
        node.destroy_node()
        rclpy.shutdown()

if __name__ == "__main__":
    # 이 스크립트 파일이 다른 모듈에 임포트되지 않고 직접 실행될 때만 main() 함수를 호출합니다.
    main()