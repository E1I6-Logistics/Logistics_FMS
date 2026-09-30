import json
import time


class OMX:
    def __init__(self, robot_id, mqtt_client):
        self.robot_id = robot_id
        self.mqtt_client = mqtt_client

        # 연결 상태
        self.connected = True
        self.last_seen = time.time()

        # 현재 작업 상태
        self.job_id = None
        self.items = {}

        self.current_count = 0
        self.total_count = 0

        self.state = "IDLE"
        self.message = ""

    # =========================================================
    # Main -> OMX
    # =========================================================

    def send_command(self, job_id, items):
        """
        로봇팔에게 작업 명령을 전송합니다.

        items 예:
        {
            "item_a": 2,
            "item_b": 1
        }
        """

        self.job_id = job_id
        self.items = items

        self.current_count = 0
        self.total_count = sum(items.values())

        self.state = "COMMAND_SENT"

        payload = {
            "job_id": job_id,
            "items": items,
        }

        topic = f"{self.robot_id}/command"

        self._publish(topic, payload)

    # =========================================================
    # OMX -> Main 데이터 처리
    # =========================================================

    def update_status(self, data):
        """
        OMX 보드의 heartbeat/status를 처리합니다.
        """

        self.connected = True
        self.last_seen = time.time()

        if "state" in data:
            self.state = data["state"]

    def update_ack(self, data):
        """
        OMX가 작업을 시작했다는 응답을 처리합니다.
        """

        self.connected = True
        self.last_seen = time.time()

        self.job_id = data.get("job_id")

        accepted = data.get("accepted", False)

        if accepted:
            self.state = "WORKING"
        else:
            self.state = "REJECTED"

    def update_progress(self, data):
        """
        현재 적재 개수를 업데이트합니다.
        """

        self.connected = True
        self.last_seen = time.time()

        self.job_id = data.get("job_id")

        self.current_count = data.get(
            "current",
            self.current_count,
        )

        self.total_count = data.get(
            "total",
            self.total_count,
        )

        self.state = "WORKING"

    def update_result(self, data):
        """
        최종 성공/실패 결과를 처리합니다.
        """

        self.connected = True
        self.last_seen = time.time()

        self.job_id = data.get("job_id")

        success = data.get("success", False)

        self.message = data.get(
            "message",
            "",
        )

        if success:
            self.state = "SUCCESS"
        else:
            self.state = "FAILED"

    # =========================================================
    # 연결 상태
    # =========================================================

    def check_connection(self, timeout=5):
        """
        마지막 heartbeat 이후 timeout초 이상 지나면
        OFFLINE으로 판단합니다.
        """

        elapsed = time.time() - self.last_seen

        if elapsed > timeout:
            self.connected = False

        return self.connected

    # =========================================================
    # MQTT Publish
    # =========================================================

    def _publish(self, topic, payload):

        message = json.dumps(payload)

        self.mqtt_client.publish(
            topic,
            message,
        )

        print(f"[OMX:{self.robot_id}] Published " f"{topic}: {payload}")
