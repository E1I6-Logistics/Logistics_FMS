"""ROS 서버/로봇 없이 실제 콜백 코드와 기존 후속 시퀀스를 검증한다."""
import importlib.util
from pathlib import Path
import sys
from threading import RLock
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from backend.app.models.robot import RobotState, NavigationType
from backend.app.services.fleet_manager import FleetManager
from test_real_navigation import graph


def load_ros_modules():
    modules = {}
    definitions = {
        "rclpy": {}, "rclpy.node": {"Node": object},
        "rclpy.publisher": {"Publisher": object},
        "rclpy.subscription": {"Subscription": object},
        "rclpy.action": {"ActionClient": object},
        "geometry_msgs.msg": {name: object for name in (
            "Quaternion", "TwistStamped", "PoseStamped", "PoseWithCovarianceStamped")},
        "nav2_msgs.action": {"FollowWaypoints": object},
        "action_msgs.msg": {"GoalStatus": SimpleNamespace(
            STATUS_SUCCEEDED=4, STATUS_CANCELED=5, STATUS_ABORTED=6)},
        "sensor_msgs.msg": {"BatteryState": object},
        "turtlebot3_my_msg.action": {"PrecisionDock": object},
        "logitle_aruco_msgs.action": {"AlignAndCorrectWithAruco": object},
        "backend.app.services.mqtt_manager": {"mqtt_manager": Mock()},
    }
    for name, attrs in definitions.items():
        module = modules[name] = ModuleType(name)
        module.__dict__.update(attrs)
    result = []
    with patch.dict(sys.modules, modules):
        for filename in ("fms_ros_node", "ros_gateway"):
            name = "backend.app.ros2._test_" + filename
            spec = importlib.util.spec_from_file_location(
                name, Path(__file__).resolve().parents[1] / "app/ros2" / (filename + ".py"))
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            result.append(module)
    return result


node_module, gateway_module = load_ros_modules()


class RosCancellationTest(unittest.TestCase):
    def setUp(self):
        self.node = node_module.FmsRosNode.__new__(node_module.FmsRosNode)
        self.node.navigation_lock = RLock()
        self.node._follow_waypoints_goal_handles = {}
        self.node._follow_waypoints_pending = set()
        self.node._follow_waypoints_cancel_callbacks = {}
        self.node.get_logger = Mock(return_value=Mock())
        self.node.navigation_result_callback = Mock()

    def test_cancel_ack_does_not_start_next_request(self):
        callback = Mock()
        handle = Mock()
        self.node._follow_waypoints_goal_handles["robot1"] = handle
        self.node.cancel_follow_waypoints("robot1", callback)
        accepted = Mock()
        accepted.result.return_value = SimpleNamespace(goals_canceling=[1])
        self.node._on_follow_waypoints_cancel("robot1", handle, accepted, callback)
        callback.assert_not_called()
        self.assertIs(self.node._follow_waypoints_goal_handles["robot1"], handle)
        terminal = Mock()
        terminal.result.return_value = SimpleNamespace(status=5)
        self.node._on_follow_waypoints_result("robot1", handle, terminal)
        callback.assert_called_once()
        self.node.navigation_result_callback.assert_not_called()

    def test_cancel_pending_goal_is_sent_after_acceptance(self):
        callback = Mock()
        self.node._follow_waypoints_pending.add("robot1")
        self.node.cancel_follow_waypoints("robot1", callback)
        callback.assert_not_called()
        handle = Mock(accepted=True)
        future = Mock()
        future.result.return_value = handle
        self.node._on_follow_waypoints_goal_response("robot1", future)
        handle.cancel_goal_async.assert_called_once()
        callback.assert_not_called()

    def test_rejected_pending_goal_unblocks_cancel(self):
        callback = Mock()
        self.node._follow_waypoints_pending.add("robot1")
        self.node.cancel_follow_waypoints("robot1", callback)
        future = Mock()
        future.result.return_value = SimpleNamespace(accepted=False)
        self.node._on_follow_waypoints_goal_response("robot1", future)
        callback.assert_called_once()
        self.node.navigation_result_callback.assert_not_called()

    def test_old_result_does_not_affect_new_handle(self):
        current, old = Mock(), Mock()
        self.node._follow_waypoints_goal_handles["robot1"] = current
        future = Mock()
        future.result.return_value = SimpleNamespace(status=4)
        self.node._on_follow_waypoints_result("robot1", old, future)
        self.assertIs(self.node._follow_waypoints_goal_handles["robot1"], current)
        self.node.navigation_result_callback.assert_not_called()


class GatewaySequenceTest(unittest.TestCase):
    def setUp(self):
        self.fleet = FleetManager()
        self.robot = self.fleet.register_robot("robot1")
        self.robot.update_pose(2., 0., .4)
        self.robot.goal_node = "2"
        self.robot.navigation_type = NavigationType.GOAL
        self.patch = patch.object(gateway_module, "fleet_manager", self.fleet)
        self.patch.start()
        self.addCleanup(self.patch.stop)
        self.gateway = gateway_module.RosGateway()
        self.node = Mock()
        self.gateway.set_ros_node(self.node)
        self.get_node = patch.object(gateway_module, "get_node", return_value={"id": "2", "x": 2., "y": 0.})
        self.get_node.start()
        self.addCleanup(self.get_node.stop)
        gateway_module.mqtt_manager.reset_mock()

    def test_charging_runs_precision_dock_only(self):
        self.robot.navigation_type = NavigationType.CHARGING
        self.gateway.on_navigation_result("robot1", 4)
        self.node.send_precision_dock.assert_called_once_with("robot1")
        self.node.send_aruco_align.assert_not_called()
        self.assertEqual(self.robot.state, RobotState.DOCKING)
        self.gateway.on_precision_dock_result("robot1", 4)
        self.assertEqual(self.robot.state, RobotState.IDLE)

    def test_return_does_not_run_docking(self):
        self.robot.navigation_type = NavigationType.RETURN
        self.gateway.on_navigation_result("robot1", 4)
        self.node.send_precision_dock.assert_not_called()
        self.node.send_aruco_align.assert_not_called()
        self.assertEqual(self.robot.state, RobotState.IDLE)

    def test_aruco_then_mqtt_keeps_order_payload(self):
        self.robot.goal_node = "5"
        self.robot.order_id = "order-1"
        self.robot.order_items = {"A": 2, "C": 3}
        self.gateway.on_navigation_result("robot1", 4)
        self.node.send_aruco_align.assert_called_once_with(robot_id="robot1", marker_id=24)
        gateway_module.mqtt_manager.send_job.assert_not_called()
        self.gateway.on_aruco_align_result("robot1", 4)
        gateway_module.mqtt_manager.send_job.assert_called_once_with(
            omx_id="omx1", job_id="order-1", items={"A": 2})
        self.assertEqual(self.robot.state, RobotState.WAITING)
        self.assertEqual(self.robot.order_items, {"A": 2, "C": 3})

    def test_segment_callback_does_not_run_final_callback_directly(self):
        self.gateway._navigation.on_result = Mock()
        self.node.navigation_result_callback("robot1", 4)
        self.gateway._navigation.on_result.assert_called_once_with("robot1", True)
        self.node.send_precision_dock.assert_not_called()
        self.node.send_aruco_align.assert_not_called()


if __name__ == "__main__":
    unittest.main()
