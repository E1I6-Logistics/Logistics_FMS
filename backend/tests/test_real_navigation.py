import unittest
from unittest.mock import patch

from backend.app.models.robot import RobotState, NavigationType
from backend.app.services.fleet_manager import FleetManager
from backend.app.services.real_navigation import RealNavigation
from backend.app.services.reservation import ReservationTable


def graph():
    points = {"0": (0., 0.), "1": (1., 0.), "2": (2., 0.), "3": (1., 1.)}
    features = [{"geometry": {"type": "Point", "coordinates": xy},
                 "properties": {"id": n}} for n, xy in points.items()]
    for a, b in [("0", "1"), ("1", "2"), ("1", "3")]:
        for start, end in [(a, b), (b, a)]:
            features.append({"properties": {"id": start + end, "startid": start, "endid": end}})
    return {"type": "FeatureCollection", "features": features}


class RealNavigationTest(unittest.TestCase):
    def setUp(self):
        self.now = 100.
        self.fleet = FleetManager()
        self.sent, self.completed, self.cancels = [], [], {}
        self.table = ReservationTable()
        self.nav = RealNavigation(
            self.fleet, lambda **kw: self.sent.append(kw), self.cancel,
            self.completed.append, {"2": 1.23}, .15,
            reservations=self.table, clock=lambda: self.now)
        self.patch = patch("backend.app.services.real_navigation.load_route_graph", graph)
        self.patch.start()
        self.addCleanup(self.patch.stop)
        self.tolerance = patch("backend.app.services.real_navigation.REAL_OCCUPANCY_TOLERANCE_M", .15)
        self.tolerance.start()
        self.addCleanup(self.tolerance.stop)
        self.robot = self.fleet.register_robot("robot1")
        self.pose(self.robot, 0., 0.)

    def cancel(self, rid, callback=None):
        self.cancels[rid] = callback

    def pose(self, robot, x, y):
        robot.update_pose(x, y, .4)
        robot.pose_received_at = self.now

    def tick(self, dt=.1):
        self.now += dt
        for robot in self.fleet.get_all_robots():
            robot.pose_received_at = self.now
        self.nav.tick()

    def request(self, target="2", kind=NavigationType.GOAL):
        self.nav.request("robot1", target, kind)
        self.tick()

    def test_full_route_uses_one_goal_and_intermediate_pose_does_not_complete_order(self):
        self.robot.order_id = "order"
        self.robot.order_items = {"A": 2}
        self.request()
        self.assertEqual(self.sent[0]["waypoints"], [(1., 0., 0.), (2., 0., 1.23)])
        self.pose(self.robot, 1., 0.)
        self.nav.on_feedback("robot1", 1)
        self.tick(100.)
        self.assertEqual(self.completed, [])
        self.assertEqual(self.robot.goal_node, "2")
        self.assertEqual(self.robot.order_items, {"A": 2})
        self.assertEqual(len(self.sent), 1)
        self.assertEqual(self.nav._robots["robot1"]["route"]["segment_index"], 1)
        self.pose(self.robot, 2., 0.)
        self.nav.on_result("robot1", True)
        self.assertEqual(self.completed, ["robot1"])
        self.assertEqual(self.robot.goal_node, "2")

    def test_next_edge_blocked_holds_at_node_then_resends_remaining_route(self):
        self.request()
        other = self.fleet.register_robot("robot2")
        self.pose(other, 2., 0.)
        other.state = RobotState.WAITING
        other.order_id = "other-work"
        self.tick()
        self.assertEqual(self.nav._hold["robot1"][0], "1")
        self.assertEqual(self.cancels, {})
        self.pose(self.robot, 1., 0.)
        self.nav.on_feedback("robot1", 1)
        self.tick()
        self.assertIn("robot1", self.cancels)
        self.cancels.pop("robot1")()
        self.assertEqual(self.robot.state, RobotState.WAITING)
        self.assertEqual(self.robot.occupied_node, "1")
        self.pose(other, 1., 1.)
        self.tick()
        self.tick()
        self.assertEqual(self.sent[-1]["waypoints"], [(2., 0., 1.23)])
        self.assertEqual(len(self.sent), 2)

    def test_disjoint_robots_each_receive_one_continuous_goal(self):
        layout = graph()
        layout["features"] += [
            {"geometry": {"type": "Point", "coordinates": [4., 0.]},
             "properties": {"id": "4"}},
            {"geometry": {"type": "Point", "coordinates": [5., 0.]},
             "properties": {"id": "5"}},
            {"properties": {"id": "45", "startid": "4", "endid": "5"}},
            {"properties": {"id": "54", "startid": "5", "endid": "4"}},
        ]
        with patch("backend.app.services.real_navigation.load_route_graph", return_value=layout):
            other = self.fleet.register_robot("robot2")
            self.pose(other, 4., 0.)
            self.nav.request("robot1", "2", NavigationType.GOAL)
            self.nav.request("robot2", "5", NavigationType.GOAL)
            self.tick()
            self.assertEqual([command["robot_id"] for command in self.sent], ["robot1", "robot2"])
            self.assertEqual(len(self.sent[0]["waypoints"]), 2)
            self.assertEqual(len(self.sent[1]["waypoints"]), 1)
            self.assertEqual(self.cancels, {})

    def test_hold_does_not_release_reservations_if_robot_left_node_before_cancel_result(self):
        self.request()
        other = self.fleet.register_robot("robot2")
        self.pose(other, 2., 0.)
        other.state = RobotState.WAITING
        other.order_id = "other-work"
        self.tick()
        self.pose(self.robot, 1., 0.)
        self.tick()
        before = self.table.snapshot()
        self.pose(self.robot, 1.3, 0.)
        self.cancels.pop("robot1")()
        self.assertEqual(self.robot.state, RobotState.PAUSED)
        self.assertEqual(self.table.snapshot(), before)
        self.assertEqual(len(self.sent), 1)

    def test_success_requires_confirmed_intermediate_progress(self):
        self.request()
        self.pose(self.robot, 2., 0.)
        self.nav.on_feedback("robot1", 1)
        self.nav.on_result("robot1", True)
        self.assertEqual(self.robot.state, RobotState.PAUSED)
        self.assertEqual(self.completed, [])
        self.assertTrue(self.table.snapshot())

    def test_pose_at_intermediate_node_advances_once_without_feedback(self):
        self.request()
        self.pose(self.robot, 1., 0.)
        self.tick(100.)
        self.assertEqual(self.nav._robots["robot1"]["route"]["segment_index"], 1)
        self.tick()
        self.assertEqual(self.nav._robots["robot1"]["route"]["segment_index"], 1)
        self.assertEqual(len(self.sent), 1)

    def test_next_edge_needs_feedback_to_confirm_skipped_node(self):
        self.request()
        self.pose(self.robot, 1.5, 0.)
        self.tick(100.)
        self.assertEqual(self.nav._robots["robot1"]["route"]["segment_index"], 0)
        self.nav.on_feedback("robot1", 1)
        self.tick()
        self.assertEqual(self.nav._robots["robot1"]["route"]["segment_index"], 1)

    def test_pose_is_not_overwritten_by_planning(self):
        self.pose(self.robot, .03, .02)
        self.request()
        self.assertEqual((self.robot.x, self.robot.y), (.03, .02))
        self.assertEqual((self.nav._robots["robot1"]["x"], self.nav._robots["robot1"]["y"]), (0., 0.))

    def test_same_node_still_sends_orientation_goal(self):
        self.request("0")
        self.assertEqual(len(self.sent), 1)
        self.assertEqual(self.completed, [])
        self.nav.on_result("robot1", True)
        self.assertEqual(self.completed, ["robot1"])

    def test_return_keeps_current_yaw(self):
        self.request("0", NavigationType.RETURN)
        self.assertEqual(self.sent[0]["waypoints"][0][2], .4)
        self.assertEqual(self.robot.navigation_type, NavigationType.RETURN)

    def test_stop_holds_reservations_until_terminal_callback(self):
        self.request()
        before = self.table.snapshot()
        self.nav.stop("robot1", lambda: self.nav.cancel_after_stop("robot1"))
        self.assertEqual(self.table.snapshot(), before)
        self.cancels.pop("robot1")()
        self.assertEqual(self.table.snapshot(), ())
        self.assertIsNone(self.robot.route)
        self.assertEqual(self.robot.occupied_node, "0")

    def test_latest_replacement_wins_while_cancel_pending(self):
        self.request()
        self.nav.stop("robot1", lambda: self.nav.request("robot1", "1", NavigationType.GOAL))
        self.nav.stop("robot1", lambda: self.nav.request("robot1", "3", NavigationType.GOAL))
        self.cancels.pop("robot1")()
        self.assertEqual(self.robot.goal_node, "3")

    def test_stale_pose_cancels_execution_without_releasing_occupancy(self):
        self.request()
        before = self.table.snapshot()
        self.now += 3.
        self.nav.tick()
        self.assertIn("robot1", self.cancels)
        self.assertEqual(self.table.snapshot(), before)
        self.assertEqual(self.robot.occupied_node, "0")

    def test_work_waiting_robot_blocks_without_becoming_concession(self):
        other = self.fleet.register_robot("robot2")
        self.pose(other, 1., 0.)
        other.state = RobotState.WAITING
        other.order_id = "other-order"
        self.request()
        self.assertEqual(self.sent, [])
        self.assertEqual(other.state, RobotState.WAITING)
        self.assertNotIn("robot2", self.nav._traffic._concession)

    def test_idle_blocker_uses_existing_concession_algorithm(self):
        other = self.fleet.register_robot("robot2")
        self.pose(other, 1., 0.)
        self.request()
        self.assertIn("robot2", self.nav._traffic._concession)
        self.assertTrue(any(command["robot_id"] == "robot2" for command in self.sent))
        self.assertEqual(self.completed, [])

    def test_failed_action_does_not_auto_restart(self):
        self.request()
        self.nav.on_result("robot1", False)
        self.tick()
        self.assertEqual(self.robot.state, RobotState.PAUSED)
        self.assertEqual(len(self.sent), 1)
        self.assertEqual(self.completed, [])
        self.assertEqual(self.table.snapshot(), ())

    def test_yield_movement_never_finishes_an_order_and_returns_to_idle(self):
        other = self.fleet.register_robot("robot2")
        self.pose(other, 1., 0.)
        self.request()
        for _ in range(1600):
            for rid, execution in list(self.nav._executing.items()):
                robot = self.fleet.get_robot(rid)
                target = {"0": (0., 0.), "1": (1., 0.), "2": (2., 0.), "3": (1., 1.)}[execution[1]]
                import math
                distance = math.dist((robot.x, robot.y), target)
                if distance <= .01:
                    self.pose(robot, *target)
                    self.nav.on_result(rid, True)
                else:
                    scale = .01 / distance
                    self.pose(robot, robot.x + (target[0] - robot.x) * scale,
                              robot.y + (target[1] - robot.y) * scale)
            self.tick(1.)
            if self.completed and not self.nav._traffic._concession:
                break
        self.assertEqual(self.completed, ["robot1"])
        self.assertEqual(other.state, RobotState.IDLE)
        self.assertIsNone(other.route)

    def test_paused_robot_can_receive_an_explicit_new_request(self):
        self.robot.state = RobotState.PAUSED
        self.request()
        self.assertEqual(len(self.sent), 1)
        self.assertEqual(self.robot.state, RobotState.MOVING)

    def test_explicit_stop_is_not_automatically_undone_by_yield(self):
        other = self.fleet.register_robot("robot2")
        self.pose(other, 1., 0.)
        self.nav.request("robot2", "3", NavigationType.GOAL)
        self.nav.cancel_after_stop("robot2")
        self.request()
        self.assertNotIn("robot2", self.nav._traffic._concession)
        self.assertFalse(any(command["robot_id"] == "robot2" for command in self.sent))

    def test_replacing_leader_waits_for_concession_to_reach_safe_node(self):
        other = self.fleet.register_robot("robot2")
        self.pose(other, 1., 0.)
        self.request()
        self.assertIn("robot2", self.nav._executing)
        self.nav.request("robot1", "3", NavigationType.GOAL)
        self.assertNotIn("robot2", self.cancels)
        self.assertEqual(self.robot.goal_node, "2")
        self.tick()
        self.pose(other, 1., 1.)
        self.nav.on_result("robot2", True)
        self.assertEqual(self.robot.goal_node, "3")

    def test_cancel_invalidates_request_waiting_for_concession_stop(self):
        other = self.fleet.register_robot("robot2")
        self.pose(other, 1., 0.)
        self.request()
        self.nav.request("robot1", "3", NavigationType.GOAL)
        self.nav.cancel_after_stop("robot1")
        self.pose(other, 1., 1.)
        self.nav.on_result("robot2", True)
        self.assertNotIn("robot1", self.nav._requests)
        self.assertIsNone(self.nav._robots["robot1"]["goal_node"])

    def test_edge_start_uses_actual_position_and_shared_timed_planner(self):
        self.pose(self.robot, .5, 0.)
        self.request()
        self.assertEqual(self.robot.occupied_edge, "01")
        self.assertIsNone(self.robot.current_node)
        self.assertEqual(self.sent[0]["waypoints"][0][:2], (1., 0.))
        self.assertEqual((self.robot.x, self.robot.y), (.5, 0.))

    def test_wide_occupancy_tolerance_keeps_exact_edge_pose_as_edge(self):
        with patch("backend.app.services.real_navigation.REAL_OCCUPANCY_TOLERANCE_M", .5):
            self.pose(self.robot, .5, 0.)
            self.request()
            self.assertEqual(self.robot.occupied_edge, "01")
            self.assertIsNone(self.robot.occupied_node)

    def test_orientation_after_on_time_arrival_does_not_cancel(self):
        self.request("1")
        self.pose(self.robot, 1., 0.)
        self.tick()
        self.tick(45.)
        self.assertEqual(self.cancels, {})
        self.assertEqual(self.robot.state, RobotState.MOVING)
        self.assertEqual(self.completed, [])
        self.nav.on_result("robot1", True)
        self.assertEqual(self.completed, ["robot1"])

    def test_arrival_is_not_rejected_because_another_robot_pose_is_stale(self):
        other = self.fleet.register_robot("robot2")
        self.pose(other, 1., 1.)
        other.state = RobotState.WAITING
        self.request("1")
        other.pose_received_at = self.now - 3.
        self.pose(self.robot, 1., 0.)
        self.nav.on_result("robot1", True)
        self.assertEqual(self.completed, ["robot1"])

    def test_success_waits_briefly_for_latest_pose(self):
        self.request("1")
        self.pose(self.robot, .7, 0.)
        self.nav.on_result("robot1", True)
        self.assertEqual(self.completed, [])
        self.assertEqual(self.robot.state, RobotState.WAITING)
        self.pose(self.robot, 1., 0.)
        self.tick()
        self.assertEqual(self.completed, ["robot1"])

    def test_invalid_pose_never_completes_arrival(self):
        self.request("1")
        self.robot.x = float("nan")
        self.nav.on_result("robot1", True)
        self.tick(3.)
        self.assertEqual(self.completed, [])
        self.assertEqual(self.robot.state, RobotState.PAUSED)

    def test_other_valid_edge_is_not_treated_as_current_route(self):
        self.request("1")
        self.pose(self.robot, 1., .5)
        self.tick()
        self.assertIn("robot1", self.cancels)
        self.assertEqual(self.robot.state, RobotState.PAUSED)

    def test_schedule_delay_does_not_cancel_active_goal_without_conflict(self):
        self.request("1")
        self.tick(20.)
        self.assertNotIn("robot1", self.cancels)
        self.assertEqual(self.robot.state, RobotState.MOVING)
        self.assertTrue(self.table.snapshot())

    def test_ambiguous_crossing_keeps_existing_stop_policy(self):
        crossing = graph()
        crossing["features"] += [
            {"geometry": {"type": "Point", "coordinates": [.5, -1.]}, "properties": {"id": "4"}},
            {"geometry": {"type": "Point", "coordinates": [.5, 1.]}, "properties": {"id": "5"}},
            {"properties": {"id": "45", "startid": "4", "endid": "5"}},
        ]
        with patch("backend.app.services.real_navigation.load_route_graph", return_value=crossing):
            self.request("1")
            self.pose(self.robot, .5, 0.)
            self.tick()
            self.assertIn("robot1", self.cancels)
            self.assertEqual(self.robot.state, RobotState.PAUSED)
            self.assertTrue(self.table.snapshot())

    def test_cancel_timeout_does_not_release_reservations_or_run_callback(self):
        self.request("1")
        callback = unittest.mock.Mock()
        self.nav.stop("robot1", callback)
        before = self.table.snapshot()
        self.tick(6.)
        self.assertEqual(self.robot.state, RobotState.PAUSED)
        self.assertEqual(self.table.snapshot(), before)
        callback.assert_not_called()
        self.cancels.pop("robot1")()
        callback.assert_not_called()

    def test_arrival_outside_tolerance_pauses_after_confirmation_window(self):
        self.request("1")
        self.pose(self.robot, .7, 0.)
        self.nav.on_result("robot1", True)
        self.tick(2.)
        self.assertEqual(self.completed, [])
        self.assertEqual(self.robot.state, RobotState.PAUSED)
        self.assertEqual(len(self.sent), 1)

    def test_late_terminal_result_does_not_clear_emergency_stop(self):
        self.request("1")
        self.robot.state = RobotState.EMERGENCY_STOP
        self.pose(self.robot, 1., 0.)
        self.nav.on_result("robot1", True)
        self.assertEqual(self.robot.state, RobotState.EMERGENCY_STOP)
        self.assertEqual(self.completed, [])

    def test_reconnect_does_not_resume_interrupted_request(self):
        self.request("1")
        self.robot.set_connected(False)
        self.tick()
        self.assertEqual(self.robot.state, RobotState.OFFLINE)
        self.robot.set_connected(True)
        self.assertEqual(self.robot.state, RobotState.PAUSED)

    def test_disconnect_does_not_clear_emergency_latch(self):
        self.robot.state = RobotState.EMERGENCY_STOP
        self.robot.set_connected(False)
        self.robot.set_connected(True)
        self.assertEqual(self.robot.state, RobotState.EMERGENCY_STOP)

    def test_graph_read_error_keeps_monitor_and_reservations(self):
        self.request("1")
        before = self.table.snapshot()
        with patch("backend.app.services.real_navigation.load_route_graph", side_effect=OSError("graph unavailable")):
            self.tick()
        self.assertEqual(self.robot.state, RobotState.PAUSED)
        self.assertEqual(self.table.snapshot(), before)
        self.assertIn("robot1", self.cancels)

    def test_observed_arrival_does_not_bypass_real_occupancy_conflict(self):
        self.request("1")
        self.pose(self.robot, 1., 0.)
        self.tick()
        other = self.fleet.register_robot("robot2")
        self.pose(other, 1., 0.)
        other.state = RobotState.WAITING
        self.tick()
        self.assertIn("robot1", self.cancels)
        self.assertEqual(self.completed, [])

    def test_failure_cleanup_with_missing_graph_does_not_drop_reservations(self):
        self.request("1")
        before = self.table.snapshot()
        with patch("backend.app.services.real_navigation.load_route_graph", side_effect=OSError("missing graph")):
            self.nav.on_result("robot1", False)
        self.assertEqual(self.robot.state, RobotState.PAUSED)
        self.assertEqual(self.table.snapshot(), before)
        self.assertEqual(self.completed, [])


if __name__ == "__main__":
    unittest.main()
