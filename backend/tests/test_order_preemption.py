"""기존 작업 교체가 종료 확인 전 새 주문을 실행하지 않는지 검증한다."""
import importlib.util
from pathlib import Path
import sys
from threading import RLock
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from backend.app.models.robot import RobotState
from backend.app.services.fleet_manager import FleetManager


def load_order_manager():
    gateway_module = ModuleType("backend.app.ros2.ros_gateway")
    gateway = Mock()
    gateway._navigation = SimpleNamespace(lock=RLock())
    gateway_module.ros_gateway = gateway
    gateway_module.NODE_OMX_MAP = {"5": "omx1", "6": "omx2", "3": "omx3", "4": "omx4"}
    gateway_module.CHARGING_STATION_NODES = {"robot1": "0", "robot2": "1", "robot3": "2"}
    mqtt_module = ModuleType("backend.app.services.mqtt_manager")
    mqtt_module.mqtt_manager = Mock()
    with patch.dict(sys.modules, {gateway_module.__name__: gateway_module,
                                  mqtt_module.__name__: mqtt_module}):
        name = "backend.app.services._test_order_manager"
        path = Path(__file__).resolve().parents[1] / "app/services/order_manager.py"
        spec = importlib.util.spec_from_file_location(name, path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    return module, gateway


order_module, gateway = load_order_manager()


class OrderPreemptionTest(unittest.TestCase):
    def setUp(self):
        self.fleet = FleetManager()
        self.robot = self.fleet.register_robot("robot1")
        self.robot.update_pose(0., 0., 0.)
        self.manager = order_module.OrderManager()
        self.patch = patch.object(order_module, "fleet_manager", self.fleet)
        self.patch.start()
        self.addCleanup(self.patch.stop)
        gateway.reset_mock()

    def test_new_order_waits_for_old_work_to_finish(self):
        self.robot.order_id = "old-order"
        self.robot.set_state(RobotState.WAITING)

        result = self.manager.create_order("robot1", {"A": 1, "B": 0, "C": 0, "D": 0}, 1, "3")

        gateway.cancel_current_work.assert_called_once()
        gateway.navigate_to_node.assert_not_called()
        self.assertEqual(self.robot.order_id, "old-order")
        gateway.cancel_current_work.call_args.args[1]()
        self.assertEqual(self.robot.order_id, result["order_id"])
        gateway.navigate_to_node.assert_called_once_with(
            robot_id="robot1", node_id="5", _order_step=True)

    def test_invalid_order_does_not_cancel_current_work(self):
        self.robot.order_id = "old-order"
        self.robot.set_state(RobotState.WAITING)
        with self.assertRaises(ValueError):
            self.manager.create_order("robot1", {"A": -1, "B": 0, "C": 0, "D": 0}, -1, "3")
        gateway.cancel_current_work.assert_not_called()

    def test_two_pickups_then_workstation_and_station_without_docking(self):
        self.robot.assign_order("order-1", {"A": 1, "B": 0, "C": 1, "D": 0}, 2,
                                ["5", "6"], "3")
        for node, omx_id, destination in (("5", "omx1", "6"), ("6", "omx2", "3"),
                                          ("3", "omx3", "0")):
            self.robot.current_node = node
            self.robot.set_state(RobotState.WAITING)
            self.manager.on_mqtt_result(SimpleNamespace(omx_id=omx_id),
                                        {"job_id": "order-1", "success": True})
            self.assertEqual(gateway.navigate_to_node.call_args.kwargs,
                             {"robot_id": "robot1", "node_id": destination,
                              "_order_step": True})
        self.assertIsNone(self.robot.order_id)
        gateway.navigate_to_charging_station.assert_not_called()

    def test_workstation_failure_pauses_and_keeps_order(self):
        self.robot.assign_order("order-1", {"A": 1}, 1, ["5"], "3")
        self.robot.current_node = "3"
        self.robot.set_state(RobotState.WAITING)
        self.manager.on_mqtt_result(SimpleNamespace(omx_id="omx3"),
                                    {"job_id": "order-1", "success": False})
        self.assertEqual(self.robot.state, RobotState.PAUSED)
        self.assertEqual(self.robot.order_id, "order-1")
        gateway.navigate_to_node.assert_not_called()
