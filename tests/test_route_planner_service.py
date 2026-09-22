"""최단 경로, 방향성, Cost 0 엣지, 미등록 노드 검사"""

import math
import unittest

from backend.app.services.route_planner import plan_route
from tests.fixtures import load_graph


class RoutePlannerServiceTest(unittest.TestCase):
    def setUp(self):
        self.graph = load_graph()

    def test_chooses_shortest_directed_path(self):
        route = plan_route("1", "3", self.graph)
        self.assertEqual(route["node_ids"], ["1", "2", "3"])
        self.assertEqual(route["edge_ids"], ["e12", "e23"])
        self.assertEqual(route["cost"], 2)

    def test_zero_cost_edge_uses_coordinate_distance(self):
        route = plan_route("1", "4", self.graph)
        self.assertEqual(route["node_ids"], ["1", "4"])
        self.assertAlmostEqual(route["cost"], math.sqrt(2))

    def test_does_not_traverse_edge_in_reverse(self):
        with self.assertRaisesRegex(ValueError, "연결된 경로가 없습니다"):
            plan_route("3", "1", self.graph)

    def test_unknown_node_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "존재하지 않는 경로 노드"):
            plan_route("1", "99", self.graph)


if __name__ == "__main__":
    unittest.main()
