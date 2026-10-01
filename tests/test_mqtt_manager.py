import json

import pytest

from backend.app.services.mqtt_manager import MQTTManager


class PublishResult:
    rc = 0


class FakeMqttClient:
    def __init__(self):
        self.published = []
        self.subscribed = []
        self.on_connect = None
        self.on_disconnect = None
        self.on_message = None

    def reconnect_delay_set(self, min_delay, max_delay):
        pass

    def subscribe(self, topic):
        self.subscribed.append(topic)

    def publish(self, topic, payload):
        self.published.append((topic, json.loads(payload)))
        return PublishResult()


class Message:
    def __init__(self, topic, payload):
        self.topic = topic
        self.payload = json.dumps(payload).encode("utf-8")


@pytest.fixture
def manager():
    client = FakeMqttClient()
    result = MQTTManager(client=client)
    result._on_connect(client, None, None, 0)
    return result


def test_status_message_discovers_omx(manager):
    manager._on_message(None, None, Message("omx1/status", {"state": "IDLE"}))

    device = manager.get_robot("omx1")
    assert device is not None
    assert device.connected is True
    assert device.state == "IDLE"


def test_command_is_published_to_connected_omx(manager):
    manager._on_message(None, None, Message("omx1/status", {"state": "IDLE"}))

    manager.send_command("omx1", "job-1", {"A": 2})

    assert manager.client.published == [
        ("omx1/command", {"job_id": "job-1", "items": {"A": 2}})
    ]
    assert manager.get_robot("omx1").state == "COMMAND_SENT"


def test_result_calls_registered_callback(manager):
    received = []
    manager.set_result_callback(lambda omx, data: received.append((omx.robot_id, data)))
    manager._on_message(None, None, Message("omx1/status", {"state": "IDLE"}))

    manager._on_message(
        None,
        None,
        Message("omx1/result", {"job_id": "job-1", "success": True}),
    )

    assert received == [("omx1", {"job_id": "job-1", "success": True})]


def test_progress_calls_registered_callback(manager):
    received = []
    manager.set_progress_callback(lambda omx, data: received.append(data))
    manager._on_message(None, None, Message("omx1/status", {"state": "IDLE"}))

    manager._on_message(
        None,
        None,
        Message("omx1/progress", {"job_id": "job-1", "current": 1, "total": 2}),
    )

    assert received == [{"job_id": "job-1", "current": 1, "total": 2}]


def test_unknown_omx_is_not_created_by_result(manager):
    manager._on_message(
        None,
        None,
        Message("unknown/result", {"job_id": "job-1", "success": True}),
    )

    assert manager.get_robot("unknown") is None


def test_send_command_rejects_disconnected_broker():
    manager = MQTTManager(client=FakeMqttClient())

    with pytest.raises(RuntimeError, match="브로커"):
        manager.send_command("omx1", "job-1", {"A": 1})
