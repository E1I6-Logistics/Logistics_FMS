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


command_sent = False


try:
    while True:

        robot = mqtt_manager.get_robot("omx1")

        # OMX가 발견되면 명령 1회 전송
        if robot is not None:

            print(
                f"[STATE] "
                f"{robot.robot_id} "
                f"connected={robot.connected} "
                f"state={robot.state} "
                f"progress="
                f"{robot.current_count}/"
                f"{robot.total_count}"
            )

            if robot.connected and not command_sent:

                print()
                print("[TEST] Command Send")

                robot.send_command(
                    job_id="test_001",
                    items={
                        "item_a": 2,
                        "item_b": 1,
                    },
                )

                command_sent = True

        time.sleep(2)


except KeyboardInterrupt:

    mqtt_manager.stop()
