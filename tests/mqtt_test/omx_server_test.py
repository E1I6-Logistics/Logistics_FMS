import time

from backend.app.services.mqtt_manager import mqtt_manager


def on_result(robot, data):
    print()
    print("==============================")
    print("OMX 작업 결과 수신")
    print("==============================")
    print(f"Robot   : {robot.robot_id}")
    print(f"Job ID  : {data['job_id']}")
    print(f"Success : {data['success']}")
    print("==============================")


mqtt_manager.set_result_callback(on_result)
mqtt_manager.start()

# 이미 명령을 보낸 OMX 저장
command_sent_robots = set()

try:
    while True:

        # 현재 발견된 모든 OMX 가져오기
        robots = mqtt_manager.get_robots()

        print()
        print("========== OMX LIST ==========")

        if len(robots) == 0:
            print("연결된 OMX 없음")

        for robot_id, robot in robots.items():

            print(
                f"{robot.robot_id} "
                f"connected={robot.connected} "
                f"state={robot.state} "
                f"progress="
                f"{robot.current_count}/"
                f"{robot.total_count}"
            )

            # 새로 발견된 OMX이고 연결 상태이면
            # 테스트 명령 1회 전송
            if robot.connected and robot_id not in command_sent_robots:
                print(f"[TEST] Command Send -> {robot_id}")

                robot.send_command(job_id=f"test_{robot_id}", items={"item_a": 2, "item_b": 1})
                command_sent_robots.add(robot_id)

        print("==============================")

        time.sleep(2)


except KeyboardInterrupt:

    mqtt_manager.stop()
