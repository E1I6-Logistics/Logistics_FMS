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

    def test_intermediate_result_does_not_complete_order(self):
        self.robot.order_id = "order"
        self.robot.order_items = {"A": 2}
        self.request()
        self.assertEqual(self.sent[0]["waypoints"][0][:2], (1., 0.))
        self.pose(self.robot, 1., 0.)
        self.nav.on_result("robot1", True)
        self.assertEqual(self.completed, [])
        self.assertEqual(self.robot.goal_node, "2")
        self.assertEqual(self.robot.order_items, {"A": 2})
        self.tick(40.)
        self.assertEqual(self.sent[-1]["waypoints"], [(2., 0., 1.23)])
        self.pose(self.robot, 2., 0.)
        self.nav.on_result("robot1", True)
        self.assertEqual(self.completed, ["robot1"])
        self.assertEqual(self.robot.goal_node, "2")

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
            self.tick()
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

    def test_replacing_leader_waits_for_moving_concession_to_stop(self):
        other = self.fleet.register_robot("robot2")
        self.pose(other, 1., 0.)
        self.request()
        self.assertIn("robot2", self.nav._executing)
        self.nav.request("robot1", "3", NavigationType.GOAL)
        self.assertIn("robot2", self.cancels)
        self.assertEqual(self.robot.goal_node, "2")
        self.tick()
        self.cancels.pop("robot2")()
        self.assertEqual(self.robot.goal_node, "3")

    def test_cancel_invalidates_request_waiting_for_concession_stop(self):
        other = self.fleet.register_robot("robot2")
        self.pose(other, 1., 0.)
        self.request()
        self.nav.request("robot1", "3", NavigationType.GOAL)
        self.nav.cancel_after_stop("robot1")
        self.cancels.pop("robot2")()
        self.assertNotIn("robot1", self.nav._requests)
        self.assertIsNone(self.nav._robots["robot1"]["goal_node"])

    def test_edge_start_uses_actual_position_and_shared_timed_planner(self):
        self.pose(self.robot, .5, 0.)
        self.request()
        self.assertEqual(self.robot.occupied_edge, "01")
        self.assertIsNone(self.robot.current_node)
        self.assertEqual(self.sent[0]["waypoints"][0][:2], (1., 0.))
        self.assertEqual((self.robot.x, self.robot.y), (.5, 0.))


if __name__ == "__main__":
    unittest.main()
