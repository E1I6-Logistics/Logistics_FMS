import json
import threading
import time

import paho.mqtt.client as mqtt

from ..models.omx import OMX


class MQTTManager:
    def __init__(
        self,
        broker_ip="localhost",
        broker_port=1883,
    ):
        self.broker_ip = broker_ip
        self.broker_port = broker_port

        # OMX 객체 저장
        self.robots = {}

        # 작업 결과 Callback
        self.result_callback = None

        # MQTT Client
        self.client = mqtt.Client()

        self.client.on_connect = self._on_connect
        self.client.on_message = self._on_message

        self.running = False
        self.connection_thread = None

    # =========================================================
    # MQTT 시작
    # =========================================================

    def start(self):
        print(f"[MQTT] Connecting to " f"{self.broker_ip}:{self.broker_port}")

        self.client.connect(
            self.broker_ip,
            self.broker_port,
            60,
        )

        self.client.loop_start()

        self.running = True

        self.connection_thread = threading.Thread(
            target=self._connection_loop,
            daemon=True,
        )

        self.connection_thread.start()

    # =========================================================
    # MQTT 종료
    # =========================================================

    def stop(self):
        self.running = False

        self.client.loop_stop()
        self.client.disconnect()

        print("[MQTT] Stopped")

    # =========================================================
    # Broker 연결 Callback
    # =========================================================

    def _on_connect(
        self,
        client,
        userdata,
        flags,
        rc,
    ):
        print(f"[MQTT] Connected: {rc}")

        client.subscribe("+/status")
        client.subscribe("+/ack")
        client.subscribe("+/progress")
        client.subscribe("+/result")

        print("[MQTT] Waiting OMX robots...")

    # =========================================================
    # 메시지 수신
    # =========================================================

    def _on_message(
        self,
        client,
        userdata,
        msg,
    ):
        topic_parts = msg.topic.split("/")

        if len(topic_parts) != 2:
            return

        robot_id = topic_parts[0]
        message_type = topic_parts[1]

        try:
            data = json.loads(msg.payload.decode())

        except Exception as e:
            print(f"[MQTT] JSON Error: {e}")
            return

        # =============================================
        # 처음 보는 OMX
        # =============================================

        if robot_id not in self.robots:

            # status 메시지가 와야 등록
            if message_type != "status":
                return

            self.robots[robot_id] = OMX(
                robot_id=robot_id,
                mqtt_client=self.client,
            )

            print()
            print(f"[MQTT] New OMX discovered: " f"{robot_id}")

        robot = self.robots[robot_id]

        # =============================================
        # 메시지 종류
        # =============================================

        if message_type == "status":
            robot.update_status(data)

        elif message_type == "ack":
            robot.update_ack(data)

            print(f"[MQTT] ACK: " f"{robot_id} / {data}")

        elif message_type == "progress":
            robot.update_progress(data)

            print(
                f"[MQTT] PROGRESS: "
                f"{robot_id} / "
                f"{robot.current_count}/"
                f"{robot.total_count}"
            )

        elif message_type == "result":
            robot.update_result(data)

            print(f"[MQTT] RESULT: " f"{robot_id} / {data}")

            if self.result_callback is not None:
                self.result_callback(
                    robot,
                    data,
                )

    # =========================================================
    # OMX 조회
    # =========================================================

    def get_robot(self, robot_id):
        return self.robots.get(robot_id)

    def get_robots(self):
        return self.robots

    # =========================================================
    # Result Callback
    # =========================================================

    def set_result_callback(self, callback):
        self.result_callback = callback

    # =========================================================
    # 연결 확인
    # =========================================================

    def _connection_loop(self):
        while self.running:

            for robot in self.robots.values():

                was_connected = robot.connected

                robot.check_connection(timeout=5)

                if was_connected and not robot.connected:
                    print(f"[MQTT] OMX OFFLINE: " f"{robot.robot_id}")

            time.sleep(1)


mqtt_manager = MQTTManager()
