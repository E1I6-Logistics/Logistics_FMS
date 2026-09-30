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

        # 발견된 OMX 객체
        self.robots = {}

        # 최종 결과를 외부 FMS 로직에 전달하기 위한 Callback
        self.result_callback = None

        # MQTT Client
        self.client = mqtt.Client()

        self.client.on_connect = self._on_connect
        self.client.on_message = self._on_message

        # 연결 상태 확인 Thread
        self.running = False
        self.connection_thread = None

    # =========================================================
    # 시작 / 종료
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

    def stop(self):

        self.running = False

        self.client.loop_stop()
        self.client.disconnect()

        print("[MQTT] Stopped")

    # =========================================================
    # MQTT Callback
    # =========================================================

    def _on_connect(
        self,
        client,
        userdata,
        flags,
        rc,
    ):

        print(f"[MQTT] Connected: {rc}")

        # 모든 OMX namespace 감지
        client.subscribe("+/status")
        client.subscribe("+/ack")
        client.subscribe("+/progress")
        client.subscribe("+/result")

        print("[MQTT] Subscribe: +/status")
        print("[MQTT] Subscribe: +/ack")
        print("[MQTT] Subscribe: +/progress")
        print("[MQTT] Subscribe: +/result")

    def _on_message(
        self,
        client,
        userdata,
        msg,
    ):

        # ---------------------------------------------
        # Topic 분석
        #
        # ex)
        # omx1/status
        #
        # namespace = omx1
        # message_type = status
        # ---------------------------------------------

        topic_parts = msg.topic.split("/")

        if len(topic_parts) != 2:
            return

        robot_id = topic_parts[0]
        message_type = topic_parts[1]

        # JSON 변환
        try:
            data = json.loads(msg.payload.decode())

        except Exception as e:
            print(f"[MQTT] JSON Error: {e}")
            return

        # ---------------------------------------------
        # 새로운 OMX 발견
        # ---------------------------------------------

        if robot_id not in self.robots:

            # status를 통해서만 신규 로봇 등록
            if message_type != "status":
                print(f"[MQTT] Unknown OMX: {robot_id}")
                return

            self.robots[robot_id] = OMX(
                robot_id=robot_id,
                mqtt_client=self.client,
            )

            print(f"[MQTT] New OMX discovered: " f"{robot_id}")

        robot = self.robots[robot_id]

        # ---------------------------------------------
        # 메시지 종류별 처리
        # ---------------------------------------------

        if message_type == "status":

            robot.update_status(data)

        elif message_type == "ack":

            robot.update_ack(data)

        elif message_type == "progress":

            robot.update_progress(data)

        elif message_type == "result":

            robot.update_result(data)

            # FMS 쪽 Callback 실행
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
    # 결과 Callback 등록
    # =========================================================

    def set_result_callback(
        self,
        callback,
    ):

        self.result_callback = callback

    # =========================================================
    # 연결 상태 확인
    # =========================================================

    def _connection_loop(self):

        while self.running:

            for robot in self.robots.values():

                was_connected = robot.connected

                robot.check_connection(timeout=5)

                if was_connected and not robot.connected:

                    print(f"[MQTT] OMX OFFLINE: " f"{robot.robot_id}")

            time.sleep(1)


# =============================================================
# FMS 전체에서 사용할 공용 Manager
# =============================================================

mqtt_manager = MQTTManager()
