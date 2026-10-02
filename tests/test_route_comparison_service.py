"""경로 유효성, 거리 재계산, 경로·거리 일치 여부 검사"""

import math
import unittest

from simulation.services.route_service import (
    build_compact_route_graph,
    build_edge_weight_lookup,
    build_route_inputs,
    compare_path_metrics,
    validate_and_calculate_path_distance,
)
from tests.fixtures import load_graph, load_responses, route_inputs


class RouteComparisonServiceTest(unittest.TestCase):
    def setUp(self):
        self.points, self.edges = route_inputs()
        self.responses = load_responses()

    # 경로 비교 로직을 변경했을 때 정답 경로를 성공으로 판정하는지 확인한다.
    def test_matching_path_is_valid(self):
        path, distance = validate_and_calculate_path_distance(
            self.points, self.edges, self.responses["matching"]["path"], 1, 3
        )
        self.assertEqual(path, [1, 2, 3])
        self.assertEqual(distance, 2)
        self.assertTrue(compare_path_metrics([1, 2, 3], 2, path, distance)["same_path"])

    # 거리 판정을 변경했을 때 모델의 거리값 대신 코드를 재계산하는지 확인한다.
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

    # 경로 유효성 검사를 변경했을 때 없는 방향성 엣지를 거부하는지 확인한다.
    def test_missing_directed_edge_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "존재하지 않는 방향성 edge"):
            validate_and_calculate_path_distance(
                self.points, self.edges, self.responses["nonexistent_edge"]["path"], 1, 3
            )

    # 도착 노드 검사를 변경했을 때 잘못 끝난 경로를 거부하는지 확인한다.
    def test_wrong_destination_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "도착 노드 불일치"):
            validate_and_calculate_path_distance(
                self.points, self.edges, self.responses["wrong_destination"]["path"], 1, 3
            )

    # 엣지 가중치 계산을 변경했을 때 planner와 같은 cost 0 규칙을 쓰는지 확인한다.
    def test_zero_cost_uses_same_weight_as_planner(self):
        weights = build_edge_weight_lookup(self.points, self.edges)
        self.assertAlmostEqual(weights[(1, 4)], math.sqrt(2))

    # 병렬 엣지 처리를 변경했을 때 가장 낮은 비용을 선택하는지 확인한다.
    def test_parallel_edges_use_lowest_cost(self):
        weights = build_edge_weight_lookup(self.points, self.edges + [(1, 3, 1.5)])
        self.assertEqual(weights[(1, 3)], 1.5)

    # Compact Graph 변환을 변경했을 때 계산된 가중치가 저장되는지 확인한다.
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


    # 명시적 weight가 있으면 cost나 좌표 거리보다 우선하는지 확인한다.
    def test_stored_weight_is_authoritative(self):
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
                    "properties": {
                        "startid": 1, "endid": 2, "cost": 99, "weight": 2.5
                    },
                },
            ],
        }
        _, edges = build_route_inputs(graph, require_stored_weight=True)
        self.assertEqual(edges, [(1, 2, 2.5)])

    # 동일 조건 벤치마크에서 weight가 빠진 Edge를 즉시 거부하는지 확인한다.
    def test_strict_input_rejects_missing_weight(self):
        with self.assertRaisesRegex(ValueError, "weight가 없습니다"):
            build_route_inputs(load_graph(), require_stored_weight=True)


if __name__ == "__main__":
    unittest.main()
