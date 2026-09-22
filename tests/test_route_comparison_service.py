"""경로 유효성, 거리 재계산, 경로·거리 일치 여부 검사"""

import math
import unittest

from backend.app.services.route_comparison_service import (
    build_compact_route_graph,
    build_edge_weight_lookup,
    compare_path_metrics,
    validate_and_calculate_path_distance,
)
from tests.fixtures import load_responses, route_inputs


class RouteComparisonServiceTest(unittest.TestCase):
    def setUp(self):
        self.points, self.edges = route_inputs()
        self.responses = load_responses()

    def test_matching_path_is_valid(self):
        path, distance = validate_and_calculate_path_distance(
            self.points, self.edges, self.responses["matching"]["path"], 1, 3
        )
        self.assertEqual(path, [1, 2, 3])
        self.assertEqual(distance, 2)
        self.assertTrue(compare_path_metrics([1, 2, 3], 2, path, distance)["same_path"])

    def test_reported_distance_does_not_affect_recalculation(self):
        response = self.responses["alternative"]
        _, distance = validate_and_calculate_path_distance(
            self.points, self.edges, response["path"], 1, 3
        )
        self.assertEqual(response["reported_total_distance"], 2)
        self.assertEqual(distance, 3)
        metrics = compare_path_metrics([1, 2, 3], 2, response["path"], distance)
        self.assertFalse(metrics["same_path"])
        self.assertFalse(metrics["same_distance"])
        self.assertEqual(metrics["distance_difference"], 1)

    def test_missing_directed_edge_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "존재하지 않는 방향성 edge"):
            validate_and_calculate_path_distance(
                self.points, self.edges, self.responses["nonexistent_edge"]["path"], 1, 3
            )

    def test_wrong_destination_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "도착 노드 불일치"):
            validate_and_calculate_path_distance(
                self.points, self.edges, self.responses["wrong_destination"]["path"], 1, 3
            )

    def test_zero_cost_uses_same_weight_as_planner(self):
        weights = build_edge_weight_lookup(self.points, self.edges)
        self.assertAlmostEqual(weights[(1, 4)], math.sqrt(2))

    def test_parallel_edges_use_lowest_cost(self):
        weights = build_edge_weight_lookup(self.points, self.edges + [(1, 3, 1.5)])
        self.assertEqual(weights[(1, 3)], 1.5)

    def test_compact_graph_precomputes_edge_weights(self):
        graph = {
            "type": "FeatureCollection",
            "features": [
                {
                    "geometry": {"type": "Point", "coordinates": [0, 0]},
                    "properties": {"id": 1},
                },
                {
                    "geometry": {"type": "Point", "coordinates": [3, 4]},
                    "properties": {"id": 2},
                },
                {
                    "geometry": {"type": "MultiLineString"},
                    "properties": {"startid": 1, "endid": 2, "cost": 0},
                },
            ],
        }

        compact = build_compact_route_graph(graph, "test.geojson")

        self.assertEqual(compact["type"], "CompactRouteGraph")
        self.assertEqual(compact["source_graph"], "test.geojson")
        self.assertEqual(compact["nodes"], [1, 2])
        self.assertEqual(compact["edges"], [{"from": 1, "to": 2, "weight": 5.0}])


if __name__ == "__main__":
    unittest.main()
