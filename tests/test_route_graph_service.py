"""GeoJSON 로딩과 노드 조회 검사"""

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from simulation.services import route_service
from tests.fixtures import MOCK_DIR, load_graph


class RouteGraphServiceTest(unittest.TestCase):
    # GeoJSON 로딩 방식을 변경했을 때 기본 그래프가 그대로 읽히는지 확인한다.
    def test_loads_fixture_geojson(self):
        with patch.object(route_service, "ROUTE_GRAPH_PATH", MOCK_DIR / "route_graph.geojson"):
            graph = route_service.load_route_graph()
        self.assertEqual(graph, load_graph())

    # 노드 조회 로직을 변경했을 때 엣지가 노드로 섞이지 않는지 확인한다.
    def test_node_lookup_ignores_edge_features(self):
        nodes = route_service.node_lookup(load_graph())
        self.assertEqual(set(nodes), {"1", "2", "3", "4"})
        self.assertEqual(nodes["4"]["geometry"]["coordinates"], [1, 1])

    # 입력 검증을 변경했을 때 잘못된 GeoJSON 구조가 거부되는지 확인한다.
    def test_rejects_non_feature_collection(self):
        with tempfile.TemporaryDirectory() as directory:
            invalid = Path(directory) / "invalid.json"
            invalid.write_text(json.dumps({"type": "Feature"}), encoding="utf-8")
            with patch.object(route_service, "ROUTE_GRAPH_PATH", invalid):
                with self.assertRaisesRegex(ValueError, "FeatureCollection"):
                    route_service.load_route_graph()

    # V2 입력은 좌표와 edge 배열 없이 방향별 adjacency와 저장 weight만 보존한다.
    def test_builds_v2_compact_adjacency_graph(self):
        graph = route_service.build_compact_adjacency_graph(
            load_graph(), "route_graph.geojson", require_stored_weight=False
        )

        self.assertEqual(graph["type"], "CompactAdjacencyGraph")
        self.assertNotIn("node_coordinates", graph)
        self.assertNotIn("edges", graph)
        self.assertEqual(
            graph["adjacency"]["1"],
            [{"to": 2, "weight": 1.0}, {"to": 3, "weight": 3.0}, {"to": 4, "weight": 2 ** 0.5}],
        )

    # 서로 반대 방향의 edge는 같은 weight로 합치지 않고 각각 유지한다.
    def test_preserves_asymmetric_directed_weights(self):
        graph = {
            "type": "CompactAdjacencyGraph",
            "nodes": [0, 1],
            "adjacency": {
                "0": [{"to": 1, "weight": 0.352}],
                "1": [{"to": 0, "weight": 0.223}],
            },
        }

        edges = route_service.compact_graph_edges(graph)

        self.assertEqual(
            edges,
            [
                {"from": 0, "to": 1, "weight": 0.352},
                {"from": 1, "to": 0, "weight": 0.223},
            ],
        )


if __name__ == "__main__":
    unittest.main()
