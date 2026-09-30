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


if __name__ == "__main__":
    unittest.main()
