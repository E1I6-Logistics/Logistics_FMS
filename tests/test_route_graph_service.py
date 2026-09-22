"""GeoJSON 로딩과 노드 조회 검사"""

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from backend.app.services import route_graph
from tests.fixtures import MOCK_DIR, load_graph


class RouteGraphServiceTest(unittest.TestCase):
    def test_loads_fixture_geojson(self):
        with patch.object(route_graph, "ROUTE_GRAPH_PATH", MOCK_DIR / "route_graph.geojson"):
            graph = route_graph.load_route_graph()
        self.assertEqual(graph, load_graph())

    def test_node_lookup_ignores_edge_features(self):
        nodes = route_graph.node_lookup(load_graph())
        self.assertEqual(set(nodes), {"1", "2", "3", "4"})
        self.assertEqual(nodes["4"]["geometry"]["coordinates"], [1, 1])

    def test_rejects_non_feature_collection(self):
        with tempfile.TemporaryDirectory() as directory:
            invalid = Path(directory) / "invalid.json"
            invalid.write_text(json.dumps({"type": "Feature"}), encoding="utf-8")
            with patch.object(route_graph, "ROUTE_GRAPH_PATH", invalid):
                with self.assertRaisesRegex(ValueError, "FeatureCollection"):
                    route_graph.load_route_graph()


if __name__ == "__main__":
    unittest.main()
