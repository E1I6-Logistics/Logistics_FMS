from __future__ import annotations

import asyncio
import math
import unittest

from backend.app.services.route_graph import get_node
from backend.app.services.route_planner import plan_route
from backend.app.services.simulation_gateway import SimulationGateway


class RouteSimulationTest(unittest.TestCase):
    def setUp(self) -> None:
        self.gateway = SimulationGateway()

        async def initialize() -> None:
            self.gateway.start()
            await self.gateway.stop()

        asyncio.run(initialize())

    def test_route_is_visible_before_motion_and_clears_on_arrival(self) -> None:
        start = self.gateway.robot_snapshot("robot1")
        response = self.gateway.navigate_to_node("robot1", 7)
        ready = self.gateway.robot_snapshot("robot1")

        self.assertEqual(response["status"], "SUCCESS")
        self.assertEqual(ready["status"], "ROUTE_READY")
        self.assertEqual(ready["route"]["node_ids"], ["2", "3", "6", "12", "7"])
        self.assertEqual(ready["route"]["edge_ids"], ["17", "18", "34", "36"])

        robot = self.gateway._get_robot("robot1")
        self.gateway._advance(robot, 0.1)
        self.assertEqual((robot.x, robot.y), (start["x"], start["y"]))
        self.assertIsNotNone(self.gateway.robot_snapshot("robot1")["route"])

        for _ in range(100):
            self.gateway._advance(robot, 1.0)
            if robot.status == "IDLE":
                break

        goal = get_node(7)
        arrived = self.gateway.robot_snapshot("robot1")
        self.assertTrue(math.isclose(arrived["x"], goal["x"]))
        self.assertTrue(math.isclose(arrived["y"], goal["y"]))
        self.assertEqual(arrived["status"], "IDLE")
        self.assertIsNone(arrived["route"])

    def test_explicit_stop_clears_active_route(self) -> None:
        self.gateway.navigate_to_node("robot1", 7)
        self.gateway.stop_robot("robot1")
        stopped = self.gateway.robot_snapshot("robot1")
        self.assertEqual(stopped["status"], "IDLE")
        self.assertIsNone(stopped["route"])

    def test_unknown_route_node_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "존재하지 않는 경로 노드"):
            plan_route("2", "missing")


if __name__ == "__main__":
    unittest.main()
