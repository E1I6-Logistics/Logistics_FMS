import json
import threading
import time

import paho.mqtt.client as mqtt

from ..models.omx import OMX
from ..config import MQTT_BROKER_IP, MQTT_BROKER_PORT


class MQTTManager:
    def __init__(self):
        self.broker_ip = MQTT_BROKER_IP
        self.broker_port = MQTT_BROKER_PORT

        # OMX 객체 저장
        self.omx_devices = {}

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
        if self.running:
            return

        print(f"[MQTT] Connecting to " f"{self.broker_ip}:{self.broker_port}")
        self.client.connect(self.broker_ip, self.broker_port, 60)

        self.client.loop_start()
        self.running = True

        self.connection_thread = threading.Thread(target=self._connection_loop, daemon=True)
        self.connection_thread.start()

    # =========================================================
    # MQTT 종료
    # =========================================================

    def stop(self):
        if not self.running:
            return
        self.running = False

        self.client.loop_stop()
        self.client.disconnect()

        if self.connection_thread is not None:
            self.connection_thread.join(timeout=2.0)

        print("[MQTT] Stopped")

    # =========================================================
    # Broker 연결 Callback
    # =========================================================

    def _on_connect(self, client, userdata, flags, rc):
        print(f"[MQTT] Connected: {rc}")

        client.subscribe("+/status")
        client.subscribe("+/ack")
        client.subscribe("+/progress")
        client.subscribe("+/result")

        print("[MQTT] Waiting OMX robots...")

    # =========================================================
    # 메시지 수신
    # =========================================================

    def _on_message(self, client, userdata, msg):
        topic_parts = msg.topic.split("/")

        if len(topic_parts) != 2:
            return

        omx_id = topic_parts[0]
        message_type = topic_parts[1]

        try:
            data = json.loads(msg.payload.decode())

        except Exception as e:
            print(f"[MQTT] JSON Error: {e}")
            return

        # =============================================
        # 처음 보는 OMX
        # =============================================

        if omx_id not in self.omx_devices:

            # status 메시지가 와야 등록
            if message_type != "status":
                return

            self.omx_devices[omx_id] = OMX(omx_id=omx_id, mqtt_client=self.client)

            print()
            print(f"[MQTT] New OMX discovered: " f"{omx_id}")

        omx = self.omx_devices[omx_id]

        # =============================================
        # 메시지 종류
        # =============================================

        if message_type == "status":
            # status 수신 전 연결 상태 저장
            was_connected = omx.connected
            # status 수신 → 연결 상태 및 last_seen 갱신
            omx.update_status(data)

            # OFFLINE 상태였던 OMX가 다시 status를 보내면 재연결
            if not was_connected:
                print(f"[MQTT] OMX RECONNECTED: {omx_id}")

        elif message_type == "ack":
            omx.update_ack(data)
            print(f"[MQTT] ACK: " f"{omx_id} / {data}")

        elif message_type == "progress":
            omx.update_progress(data)
            print(f"[MQTT] PROGRESS: " f"{omx_id} / " f"{omx.current_count}/" f"{omx.total_count}")

        elif message_type == "result":
            omx.update_result(data)
            print(f"[MQTT] RESULT: " f"{omx_id} / {data}")

            if self.result_callback is not None:
                self.result_callback(omx, data)

    # =========================================================
    # OMX 작업 명령
    # =========================================================

    def send_job(self, omx_id, job_id, items):
        omx = self.get_omx(omx_id)

        if omx is None:
            raise ValueError(f"OMX not found: {omx_id}")

        if not omx.connected:
            raise RuntimeError(f"OMX is offline: {omx_id}")

        omx.send_command(job_id=job_id, items=items)

    # =========================================================
    # OMX 조회
    # =========================================================

    def get_omx(self, omx_id):
        return self.omx_devices.get(omx_id)

    def get_all_omx(self):
        return self.omx_devices

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

            for omx in self.omx_devices.values():

                was_connected = omx.connected

                omx.check_connection(timeout=5)

                if was_connected and not omx.connected:
                    print(f"[MQTT] OMX OFFLINE: " f"{omx.omx_id}")

            time.sleep(1)


mqtt_manager = MQTTManager()
