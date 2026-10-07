"""Broker 없이 중복 Result와 취소 후 종료 확인 흐름을 검증한다."""
import importlib.util
import json
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from backend.app.models.omx import OMX


def load_mqtt_manager():
    paho = ModuleType("paho")
    mqtt = ModuleType("paho.mqtt")
    client = ModuleType("paho.mqtt.client")
    client.Client = Mock(return_value=Mock())
    paho.mqtt = mqtt
    mqtt.client = client
    with patch.dict(sys.modules, {"paho": paho, "paho.mqtt": mqtt,
                                  "paho.mqtt.client": client}):
        name = "backend.app.services._test_mqtt_manager"
        path = Path(__file__).resolve().parents[1] / "app/services/mqtt_manager.py"
        spec = importlib.util.spec_from_file_location(name, path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    return module.MQTTManager


MQTTManager = load_mqtt_manager()


class MQTTExceptionTest(unittest.TestCase):
    def setUp(self):
        self.manager = MQTTManager()
        self.manager.omx_devices["omx1"] = OMX("omx1", self.manager.client)
        self.manager.set_result_callback(Mock())

    def message(self, topic, data):
        self.manager._on_message(None, None, SimpleNamespace(
            topic=topic, payload=json.dumps(data).encode()))

    def test_duplicate_result_advances_order_once(self):
        self.manager.send_job("omx1", "order-1", {"A": 1})
        result = {"job_id": "order-1", "success": True}
        self.message("omx1/result", result)
        self.message("omx1/result", result)
        self.manager.result_callback.assert_called_once()

    def test_new_work_waits_for_cancelled_omx_job_terminal_result(self):
        self.manager.send_job("omx1", "order-1", {"A": 1})
        callback = Mock()
        self.assertFalse(self.manager.cancel_job("order-1", callback))
        self.assertTrue(self.manager.has_active_job("order-1"))
        callback.assert_not_called()
        self.message("omx1/result", {"job_id": "order-1", "success": True})
        callback.assert_called_once()
        self.manager.result_callback.assert_not_called()
        self.assertFalse(self.manager.has_active_job("order-1"))

    def test_rejected_ack_finishes_pending_job_once(self):
        self.manager.send_job("omx1", "order-1", {"A": 1})
        self.message("omx1/ack", {"job_id": "order-1", "accepted": False})
        self.message("omx1/result", {"job_id": "order-1", "success": False})
        self.manager.result_callback.assert_called_once()
        self.assertFalse(self.manager.has_active_job("order-1"))
