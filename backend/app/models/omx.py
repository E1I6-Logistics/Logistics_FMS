import json
import time


class OMX:
    def __init__(self, omx_id, mqtt_client):
        self.omx_id = omx_id
        self.mqtt_client = mqtt_client

        # 연결 상태
        self.connected = True
        self.last_seen = time.time()

        # 현재 작업 정보
        self.job_id = None
        self.items = {}

        self.current_count = 0
        self.total_count = 0

        # 작업 진행 상태
        self.state = "IDLE"
        self.message = ""

    # =========================================================
    # Main -> OMX 명령
    # =========================================================

    def send_command(self, job_id, items):
        self.job_id = job_id
        self.items = items

        self.current_count = 0
        self.total_count = sum(items.values())

        self.state = "COMMAND_SENT"

        payload = {
            "job_id": job_id,
            "items": items,
        }

        topic = f"{self.omx_id}/command"

        self._publish(topic, payload)

    # =========================================================
    # OMX -> Main 상태 처리
    # =========================================================

    def update_status(self, data):
        self.connected = True
        self.last_seen = time.time()

        if "state" in data:
            self.state = data["state"]

    def update_ack(self, data):
        self.connected = True
        self.last_seen = time.time()

        self.job_id = data.get("job_id")

        if data.get("accepted", False):
            self.state = "WORKING"
        else:
            self.state = "REJECTED"

    def update_progress(self, data):
        self.connected = True
        self.last_seen = time.time()

        self.job_id = data.get("job_id")

        self.current_count = data.get("current", self.current_count)
        self.total_count = data.get("total", self.total_count)

        self.state = "WORKING"

    def update_result(self, data):
        self.connected = True
        self.last_seen = time.time()

        self.job_id = data.get("job_id")

        success = data.get("success", False)

        self.message = data.get("message", "")

        if success:
            self.state = "SUCCESS"
        else:
            self.state = "FAILED"

    # =========================================================
    # 연결 상태
    # =========================================================

    def check_connection(self, timeout=5):
        elapsed = time.time() - self.last_seen

        if elapsed > timeout:
            self.connected = False

        return self.connected

    # =========================================================
    # MQTT Publish
    # =========================================================

    def _publish(self, topic, payload):
        message = json.dumps(payload)
        self.mqtt_client.publish(topic, message)

        print(f"[OMX:{self.omx_id}] " f"Published {topic}: {payload}")
