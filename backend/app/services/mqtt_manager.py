from __future__ import annotations

import json
import logging
import threading
import time
from typing import Callable

try:
    import paho.mqtt.client as mqtt
except ImportError:  # 패키지가 없어도 FMS 전체가 시작 실패하지 않게 한다.
    mqtt = None

from ..config import MQTT_BROKER_HOST, MQTT_BROKER_PORT, MQTT_DEVICE_TIMEOUT_SECONDS
from ..models.omx import OMX


logger = logging.getLogger("fms.mqtt")


def _reason_code_value(reason_code) -> int:
    return int(getattr(reason_code, "value", reason_code))


class MQTTManager:
    """FMS와 OMX 사이의 MQTT 연결을 관리한다."""

    def __init__(
        self,
        broker_ip: str = MQTT_BROKER_HOST,
        broker_port: int = MQTT_BROKER_PORT,
        client=None,
    ) -> None:
        self.broker_ip = broker_ip
        self.broker_port = broker_port
        self.robots: dict[str, OMX] = {}
        self.result_callback: Callable[[OMX, dict], None] | None = None
        self.progress_callback: Callable[[OMX, dict], None] | None = None
        self._lock = threading.RLock()
        self.running = False
        self.broker_connected = False
        self.last_error: str | None = None
        self._last_connect_warning_at = 0.0
        self.connection_thread: threading.Thread | None = None

        if client is not None:
            self.client = client
        elif mqtt is not None:
            self.client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
        else:
            self.client = None

        if self.client is not None:
            self.client.on_connect = self._on_connect
            self.client.on_connect_fail = self._on_connect_fail
            self.client.on_disconnect = self._on_disconnect
            self.client.on_message = self._on_message
            if hasattr(self.client, "reconnect_delay_set"):
                self.client.reconnect_delay_set(min_delay=1, max_delay=30)

    def start(self) -> bool:
        """MQTT 연결을 시작한다. 브로커 장애는 백엔드 시작 실패로 만들지 않는다."""
        if self.running:
            return True
        if self.client is None:
            self.last_error = "paho-mqtt 패키지가 설치되어 있지 않습니다."
            logger.error("event=mqtt_start_failed error=%s", self.last_error)
            return False

        self.running = True
        try:
            # 비동기 연결이므로 브로커가 꺼져 있어도 FastAPI 시작을 막지 않는다.
            self.client.connect_async(self.broker_ip, self.broker_port, 60)
            self.client.loop_start()
        except Exception as exc:
            self.running = False
            self.last_error = str(exc)
            logger.exception(
                "event=mqtt_start_failed broker=%s port=%s",
                self.broker_ip,
                self.broker_port,
            )
            return False

        self.connection_thread = threading.Thread(
            target=self._connection_loop,
            daemon=True,
            name="fms-mqtt-monitor",
        )
        self.connection_thread.start()
        logger.info("event=mqtt_start broker=%s port=%s", self.broker_ip, self.broker_port)
        return True

    def stop(self) -> None:
        if not self.running:
            return
        self.running = False
        self.broker_connected = False
        try:
            self.client.disconnect()
        except Exception:
            logger.exception("event=mqtt_disconnect_failed")
        finally:
            self.client.loop_stop()
        if self.connection_thread is not None:
            self.connection_thread.join(timeout=2.0)
        logger.info("event=mqtt_stopped")

    def _on_connect(self, client, userdata, flags, reason_code, properties=None) -> None:
        result_code = _reason_code_value(reason_code)
        if result_code != 0:
            self.broker_connected = False
            self.last_error = f"MQTT 연결 실패 코드: {result_code}"
            logger.warning("event=mqtt_connect_rejected code=%s", result_code)
            return

        self.broker_connected = True
        self.last_error = None
        for topic in ("+/status", "+/ack", "+/progress", "+/result"):
            client.subscribe(topic)
        logger.info("event=mqtt_connected broker=%s port=%s", self.broker_ip, self.broker_port)

    def _on_connect_fail(self, client, userdata) -> None:
        self.broker_connected = False
        self.last_error = f"MQTT 브로커 연결 실패: {self.broker_ip}:{self.broker_port}"
        now = time.monotonic()
        if now - self._last_connect_warning_at >= 10.0:
            self._last_connect_warning_at = now
            logger.warning(
                "event=mqtt_connect_failed broker=%s port=%s",
                self.broker_ip,
                self.broker_port,
            )

    def _on_disconnect(
        self, client, userdata, disconnect_flags, reason_code=None, properties=None
    ) -> None:
        # reason_code가 없는 호출은 테스트용 또는 paho 1.x 형식이다.
        code = _reason_code_value(
            disconnect_flags if reason_code is None else reason_code
        )
        self.broker_connected = False
        if self.running:
            self.last_error = f"MQTT 연결 끊김 코드: {code}"
            logger.warning("event=mqtt_disconnected code=%s", code)

    def _on_message(self, client, userdata, msg) -> None:
        topic_parts = msg.topic.split("/")
        if len(topic_parts) != 2:
            logger.warning("event=mqtt_topic_invalid topic=%s", msg.topic)
            return

        omx_id, message_type = topic_parts
        if message_type not in {"status", "ack", "progress", "result"}:
            return

        try:
            data = json.loads(msg.payload.decode("utf-8"))
            if not isinstance(data, dict):
                raise ValueError("JSON object가 아닙니다.")
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
            logger.warning("event=mqtt_message_invalid topic=%s error=%s", msg.topic, exc)
            return

        callback = None
        omx = None
        with self._lock:
            omx = self.robots.get(omx_id)
            if omx is None:
                if message_type != "status":
                    logger.warning(
                        "event=mqtt_unknown_omx_message omx_id=%s type=%s",
                        omx_id,
                        message_type,
                    )
                    return
                omx = OMX(robot_id=omx_id, mqtt_client=self.client)
                self.robots[omx_id] = omx
                logger.info("event=omx_discovered omx_id=%s", omx_id)

            if message_type == "status":
                omx.update_status(data)
            elif message_type == "ack":
                omx.update_ack(data)
                logger.info(
                    "event=omx_command_ack omx_id=%s job_id=%s accepted=%s",
                    omx_id,
                    data.get("job_id"),
                    data.get("accepted"),
                )
            elif message_type == "progress":
                omx.update_progress(data)
                callback = self.progress_callback
            elif message_type == "result":
                omx.update_result(data)
                callback = self.result_callback
                logger.info(
                    "event=omx_result omx_id=%s job_id=%s success=%s",
                    omx_id,
                    data.get("job_id"),
                    data.get("success"),
                )

        # 콜백에서 다음 ROS 명령을 보낼 수 있으므로 lock 밖에서 호출한다.
        if callback is not None and omx is not None:
            try:
                callback(omx, data)
            except Exception:
                logger.exception(
                    "event=omx_result_callback_failed omx_id=%s job_id=%s",
                    omx_id,
                    data.get("job_id"),
                )

    def send_command(
        self,
        omx_id: str,
        job_id: str,
        items: dict[str, int],
        operation: str | None = None,
        total_count: int | None = None,
    ) -> None:
        if not self.broker_connected:
            raise RuntimeError("MQTT 브로커가 연결되어 있지 않습니다.")

        with self._lock:
            omx = self.robots.get(omx_id)
            if omx is None or not omx.check_connection(MQTT_DEVICE_TIMEOUT_SECONDS):
                raise RuntimeError(f"OMX가 연결되어 있지 않습니다: {omx_id}")

            payload_data = {"job_id": job_id, "items": items}
            if operation is not None:
                payload_data["operation"] = operation
            if total_count is not None:
                payload_data["total_count"] = total_count
            payload = json.dumps(payload_data)
            result = self.client.publish(f"{omx_id}/command", payload)
            if getattr(result, "rc", 0) != 0:
                raise RuntimeError(f"OMX 명령 발행에 실패했습니다: {omx_id}")

            omx.job_id = job_id
            omx.items = items.copy()
            omx.current_count = 0
            omx.total_count = sum(items.values())
            omx.state = "COMMAND_SENT"

        logger.info(
            "event=omx_command_sent omx_id=%s job_id=%s items=%s",
            omx_id,
            job_id,
            items,
        )

    def get_robot(self, robot_id: str) -> OMX | None:
        with self._lock:
            return self.robots.get(robot_id)

    def get_robots(self) -> dict[str, OMX]:
        with self._lock:
            return dict(self.robots)

    def snapshots(self) -> list[dict]:
        with self._lock:
            rows = []
            for omx in self.robots.values():
                omx.check_connection(MQTT_DEVICE_TIMEOUT_SECONDS)
                rows.append(
                    {
                        "omx_id": omx.robot_id,
                        "connected": omx.connected,
                        "state": omx.state,
                        "job_id": omx.job_id,
                        "items": dict(omx.items),
                        "current_count": omx.current_count,
                        "total_count": omx.total_count,
                        "message": omx.message,
                        "last_seen_seconds_ago": round(max(0.0, time.time() - omx.last_seen), 1),
                    }
                )
            return sorted(rows, key=lambda row: row["omx_id"])

    def status(self) -> dict:
        return {
            "enabled": True,
            "running": self.running,
            "broker_connected": self.broker_connected,
            "broker": self.broker_ip,
            "port": self.broker_port,
            "last_error": self.last_error,
        }

    def set_result_callback(self, callback: Callable[[OMX, dict], None]) -> None:
        self.result_callback = callback

    def set_progress_callback(self, callback: Callable[[OMX, dict], None]) -> None:
        self.progress_callback = callback

    def _connection_loop(self) -> None:
        while self.running:
            with self._lock:
                for omx in self.robots.values():
                    was_connected = omx.connected
                    omx.check_connection(MQTT_DEVICE_TIMEOUT_SECONDS)
                    if was_connected and not omx.connected:
                        logger.warning("event=omx_offline omx_id=%s", omx.robot_id)
            time.sleep(1)


mqtt_manager = MQTTManager()
