import time
import math
import json
import zenoh

def on_goal_received(sample):
    payload = sample.payload.to_bytes().decode('utf-8')
    print(f"\n[Robot1 Goal 수신] -> {payload}\n")

def main():
    conf = zenoh.Config()
    conf.insert_json5("connect/endpoints", '["tcp/127.0.0.1:7447"]')
    session = zenoh.open(conf)
    print(" -> Mock Robot 1 구동 완료 (Zenoh 연결 수립)")

    # 목표 지점 토픽 구독
    session.declare_subscriber("robot1/goal", on_goal_received)

    angle = 0.0
    battery = 100.0

    try:
        while True:
            # 원형 주행 모의 좌표 계산 (반경 3m)
            x = 3.0 * math.cos(angle)
            y = 3.0 * math.sin(angle)
            yaw = angle + (math.pi / 2.0)
            battery = max(10.0, battery - 0.05)

            payload = {
                "robot_id": "robot1",
                "x": round(x, 2),
                "y": round(y, 2),
                "yaw": round(yaw, 2),
                "battery": round(battery, 1),
                "status": "NAVIGATING"
            }

            session.put("robot1/telemetry", json.dumps(payload).encode('utf-8'))
            print(f"[전송] robot1 | x={payload['x']}, y={payload['y']}, 배터리={payload['battery']}%", end="\r")

            angle += 0.05
            time.sleep(0.5)
    except KeyboardInterrupt:
        print("\n가상 로봇 종료")
    finally:
        session.close()

if __name__ == "__main__":
    main()
