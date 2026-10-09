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
        "nav2_msgs.action": {"NavigateThroughPoses": SimpleNamespace(
            Goal=lambda: SimpleNamespace())},
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
        self.node._follow_waypoints_feedback_tokens = {}
        self.node._follow_waypoints_feedback_last = {}
        self.node._result_query_at = {}
        self.node._result_query_count = {}
        self.node._auxiliary_goals = {}
        self.node._follow_waypoints_clients = {}
        self.node.get_logger = Mock(return_value=Mock())
        self.node.navigation_result_callback = Mock()

    def test_registers_navigate_through_poses_action(self):
        self.node._registered_robots = set()
        self.node._cmd_vel_publishers = {}
        self.node._pose_subscribers = {}
        self.node._battery_subscribers = {}
        self.node._precision_dock_clients = {}
        self.node._aruco_align_clients = {}
        self.node.create_publisher = Mock()
        self.node.create_subscription = Mock()
        with patch.object(node_module, "ActionClient") as action_client:
            self.node.register_robot("robot1")
        action_client.assert_any_call(
            self.node, node_module.NavigateThroughPoses, "/robot1/navigate_through_poses")

    def test_sends_all_route_poses_in_one_goal(self):
        client = Mock()
        self.node._follow_waypoints_clients["robot1"] = client
        self.node.get_clock = Mock(return_value=SimpleNamespace(
            now=lambda: SimpleNamespace(to_msg=lambda: "stamp")))
        def pose_stamped():
            return SimpleNamespace(
                header=SimpleNamespace(),
                pose=SimpleNamespace(position=SimpleNamespace(), orientation=SimpleNamespace()))
        with patch.object(node_module, "PoseStamped", side_effect=pose_stamped):
            self.node.send_follow_waypoints_goal(
                "robot1", [(1., 0., 0.), (2., 0., .5), (3., 0., 1.)])
        goal = client.send_goal_async.call_args.args[0]
        self.assertEqual(len(goal.poses), 3)
        self.assertEqual([pose.pose.position.x for pose in goal.poses], [1., 2., 3.])
        self.assertEqual([pose.header.frame_id for pose in goal.poses], ["map"] * 3)
        self.assertEqual(self.node._follow_waypoints_feedback_tokens["robot1"][1], 3)
        client.send_goal_async.assert_called_once()

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

    def test_result_future_exception_keeps_current_handle_and_reports_failure(self):
        handle, future = Mock(), Mock()
        future.result.side_effect = RuntimeError("lost result")
        self.node._follow_waypoints_goal_handles["robot1"] = handle
        self.node.navigation_error_callback = Mock()
        self.node._on_follow_waypoints_result("robot1", handle, future)
        self.assertIs(self.node._follow_waypoints_goal_handles["robot1"], handle)
        self.node.navigation_error_callback.assert_called_once()
        self.node.navigation_result_callback.assert_not_called()

    def test_cancelled_goal_requeries_result_but_waits_for_terminal(self):
        handle, callback = Mock(), Mock()
        self.node._follow_waypoints_goal_handles["robot1"] = handle
        self.node._follow_waypoints_cancel_callbacks["robot1"] = callback
        self.node._result_query_at["robot1"] = 100.
        self.node._result_query_count["robot1"] = 1
        with patch.object(node_module, "monotonic", return_value=106.):
            self.node.reconcile_navigation_results()
        handle.get_result_async.assert_called_once()
        callback.assert_not_called()
        terminal = Mock()
        terminal.result.return_value = SimpleNamespace(status=5)
        self.node._on_follow_waypoints_result("robot1", handle, terminal)
        callback.assert_called_once()
        self.assertNotIn("robot1", self.node._follow_waypoints_goal_handles)

    def test_result_requery_is_bounded(self):
        handle = Mock()
        self.node._follow_waypoints_goal_handles["robot1"] = handle
        self.node._follow_waypoints_cancel_callbacks["robot1"] = Mock()
        self.node._result_query_at["robot1"] = 100.
        self.node._result_query_count["robot1"] = node_module.RESULT_QUERY_LIMIT
        with patch.object(node_module, "monotonic", return_value=1000.):
            self.node.reconcile_navigation_results()
        handle.get_result_async.assert_not_called()

    def test_old_failed_future_does_not_affect_new_goal(self):
        handle, future = Mock(), Mock()
        future.result.side_effect = RuntimeError("old result")
        self.node._follow_waypoints_goal_handles["robot1"] = handle
        self.node.navigation_error_callback = Mock()
        self.node._on_follow_waypoints_result("robot1", Mock(), future)
        future.result.assert_not_called()
        self.node.navigation_error_callback.assert_not_called()

    def test_cancel_rejected_keeps_handle_and_does_not_run_next_command(self):
        handle, future, callback = Mock(), Mock(), Mock()
        self.node._follow_waypoints_goal_handles["robot1"] = handle
        self.node._follow_waypoints_cancel_callbacks["robot1"] = callback
        self.node.navigation_error_callback = Mock()
        future.result.return_value = SimpleNamespace(goals_canceling=[])
        self.node._on_follow_waypoints_cancel("robot1", handle, future, callback)
        callback.assert_not_called()
        self.node.navigation_error_callback.assert_called_once_with("robot1", "cancel_rejected")
        self.assertIs(self.node._follow_waypoints_goal_handles["robot1"], handle)

    def test_success_result_reaches_existing_navigation_callback(self):
        handle, future = Mock(), Mock()
        self.node._follow_waypoints_goal_handles["robot1"] = handle
        future.result.return_value = SimpleNamespace(
            status=4, result=SimpleNamespace(error_code=0, error_msg=""))
        self.node._on_follow_waypoints_result("robot1", handle, future)
        self.node.navigation_result_callback.assert_called_once_with("robot1", 4)

    def test_abort_result_reaches_existing_navigation_callback(self):
        handle, future = Mock(), Mock()
        self.node._follow_waypoints_goal_handles["robot1"] = handle
        future.result.return_value = SimpleNamespace(status=6)
        self.node._on_follow_waypoints_result("robot1", handle, future)
        self.node.navigation_result_callback.assert_called_once_with("robot1", 6)

    def test_old_goal_feedback_does_not_update_new_goal(self):
        current = (object(), 3)
        self.node._follow_waypoints_feedback_tokens["robot1"] = current
        self.node.navigation_feedback_callback = Mock()
        feedback = SimpleNamespace(feedback=SimpleNamespace(number_of_poses_remaining=2))
        self.node._on_follow_waypoints_feedback("robot1", feedback, object())
        self.node.navigation_feedback_callback.assert_not_called()
        self.node._on_follow_waypoints_feedback("robot1", feedback, current)
        self.node.navigation_feedback_callback.assert_called_once_with("robot1", 1)

    def test_remaining_poses_are_clamped_to_route_indices(self):
        token = (object(), 3)
        self.node._follow_waypoints_feedback_tokens["robot1"] = token
        self.node.navigation_feedback_callback = Mock()
        for remaining in (3, 2, 1, 0):
            feedback = SimpleNamespace(feedback=SimpleNamespace(
                number_of_poses_remaining=remaining))
            self.node._on_follow_waypoints_feedback("robot1", feedback, token)
        self.assertEqual(
            [call.args[1] for call in self.node.navigation_feedback_callback.call_args_list],
            [0, 1, 2, 2])

    def test_auxiliary_cancel_waits_for_terminal_result(self):
        handle = Mock()
        entry = {"kind": "ArUco", "handle": handle,
                 "cancel_callback": None, "cancel_sent": False}
        self.node._auxiliary_goals["robot1"] = entry
        callback, result_callback = Mock(), Mock()

        self.node.cancel_auxiliary("robot1", callback)
        handle.cancel_goal_async.assert_called_once()
        callback.assert_not_called()
        response = Mock()
        response.result.return_value = SimpleNamespace(goals_canceling=[1])
        self.node._on_auxiliary_cancel("robot1", entry, response)
        callback.assert_not_called()

        self.node._finish_auxiliary("robot1", entry, 5, result_callback)
        callback.assert_called_once()
        result_callback.assert_not_called()
        self.assertFalse(self.node.has_active_auxiliary("robot1"))

    def test_auxiliary_cancel_pending_goal_after_acceptance(self):
        entry = {"kind": "PrecisionDock", "handle": None,
                 "cancel_callback": None, "cancel_sent": False}
        self.node._auxiliary_goals["robot1"] = entry
        self.node.precision_dock_result_callback = Mock()
        callback = Mock()
        self.node.cancel_auxiliary("robot1", callback)
        handle = Mock(accepted=True)
        response = Mock()
        response.result.return_value = handle
        self.node._on_precision_dock_goal_response("robot1", response, entry)
        handle.cancel_goal_async.assert_called_once()
        callback.assert_not_called()
        terminal = Mock()
        terminal.result.return_value = SimpleNamespace(status=5)
        self.node._on_precision_dock_result("robot1", terminal, entry)
        callback.assert_called_once()
        self.node.precision_dock_result_callback.assert_not_called()


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
        self.node.has_active_auxiliary.return_value = False
        self.gateway.set_ros_node(self.node)
        self.get_node = patch.object(gateway_module, "get_node", return_value={"id": "2", "x": 2., "y": 0.})
        self.get_node.start()
        self.addCleanup(self.get_node.stop)
        gateway_module.mqtt_manager.reset_mock(return_value=True, side_effect=True)

    def test_single_missing_snapshot_does_not_disconnect_robot(self):
        with patch.object(gateway_module, "monotonic", side_effect=[100., 106.]):
            self.gateway.sync_connected_robots([])
            self.assertTrue(self.robot.connected)
            self.gateway.sync_connected_robots([])
        self.assertFalse(self.robot.connected)

    def test_new_goal_waits_for_aruco_terminal_result(self):
        self.robot.set_state(RobotState.DOCKING)
        self.node.has_active_auxiliary.return_value = True
        self.gateway._navigation.stop = Mock()

        self.gateway.navigate_to_node("robot1", "2")
        self.node.cancel_auxiliary.assert_called_once()
        self.gateway._navigation.stop.assert_not_called()
        self.node.cancel_auxiliary.call_args.kwargs["callback"]()
        self.gateway._navigation.stop.assert_called_once()

    def test_new_goal_waits_for_omx_terminal_result(self):
        self.robot.order_id = "old-order"
        self.robot.set_state(RobotState.WAITING)
        self.gateway._navigation.stop = Mock()
        gateway_module.mqtt_manager.cancel_job.return_value = False

        self.gateway.navigate_to_node("robot1", "2")
        self.assertIsNone(self.robot.order_id)
        self.gateway._navigation.stop.assert_not_called()
        self.gateway._on_omx_terminal("robot1", "old-order")
        self.gateway._navigation.stop.assert_called_once()

    def test_emergency_stop_discards_goal_queued_behind_omx(self):
        self.robot.order_id = "old-order"
        self.robot.set_state(RobotState.WAITING)
        self.gateway._navigation.stop = Mock()
        gateway_module.mqtt_manager.cancel_job.return_value = False

        self.gateway.navigate_to_node("robot1", "2")
        self.gateway.emergency_stop("robot1")
        self.gateway._on_omx_terminal("robot1", "old-order")

        self.assertEqual(self.robot.state, RobotState.EMERGENCY_STOP)
        self.gateway._navigation.stop.assert_called_once()
        self.assertEqual(self.gateway._navigation.stop.call_args.kwargs["reason"],
                         "emergency_stop")
        self.assertNotIn("robot1", self.gateway._waiting_omx)

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
        self.gateway._navigation.on_result.assert_called_once_with("robot1", True, status=4)
        self.node.send_precision_dock.assert_not_called()
        self.node.send_aruco_align.assert_not_called()

    def test_nan_pose_does_not_start_docking(self):
        self.robot.goal_node = "5"
        self.robot.x = float("nan")
        self.gateway.on_navigation_result("robot1", 4)
        self.assertEqual(self.robot.state, RobotState.PAUSED)
        self.node.send_aruco_align.assert_not_called()
        self.node.send_precision_dock.assert_not_called()

    def test_outside_arrival_tolerance_does_not_start_docking(self):
        self.robot.goal_node = "5"
        self.robot.x = 1.8
        self.gateway.on_navigation_result("robot1", 4)
        self.assertEqual(self.robot.state, RobotState.PAUSED)
        self.node.send_aruco_align.assert_not_called()

    def test_stale_pose_does_not_start_docking(self):
        self.robot.goal_node = "5"
        self.robot.pose_received_at -= 10.
        self.gateway.on_navigation_result("robot1", 4)
        self.assertEqual(self.robot.state, RobotState.PAUSED)
        self.node.send_aruco_align.assert_not_called()

    def test_invalid_new_request_does_not_cancel_existing_navigation(self):
        self.robot.connected = False
        with self.assertRaises(ValueError):
            self.gateway.navigate_to_node("robot1", "2")
        self.node.cancel_follow_waypoints.assert_not_called()

    def test_repeating_active_goal_does_not_cancel_it(self):
        self.robot.set_state(RobotState.MOVING)
        self.gateway._navigation._requests["robot1"] = ("2", NavigationType.GOAL)

        self.gateway.navigate_to_node("robot1", "2")
        self.gateway.navigate_to_node("robot1", "2")

        self.node.cancel_follow_waypoints.assert_not_called()
        self.assertNotIn("robot1", self.gateway._navigation._stopping)

    def test_emergency_stop_still_sends_zero_after_cancel_timeout(self):
        self.gateway._navigation._stopping["robot1"] = None

        self.gateway.emergency_stop("robot1")

        self.node.publish_cmd_vel.assert_called_once_with(
            robot_id="robot1", linear_x=0.0, angular_z=0.0)
        self.assertEqual(self.robot.state, RobotState.EMERGENCY_STOP)

    def test_late_docking_result_keeps_emergency_state(self):
        self.robot.state = RobotState.EMERGENCY_STOP
        self.gateway.on_precision_dock_result("robot1", 4)
        self.gateway.on_aruco_align_result("robot1", 4)
        self.assertEqual(self.robot.state, RobotState.EMERGENCY_STOP)
        gateway_module.mqtt_manager.send_job.assert_not_called()

    def test_zero_velocity_during_docking_keeps_docking_state(self):
        self.robot.state = RobotState.DOCKING
        self.gateway.cmd_vel("robot1", 0., 0.)
        self.assertEqual(self.robot.state, RobotState.DOCKING)
        with self.assertRaises(ValueError):
            self.gateway.cmd_vel("robot1", .1, 0.)


if __name__ == "__main__":
    unittest.main()
