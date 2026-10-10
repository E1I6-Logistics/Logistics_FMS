"""최단 경로, 방향성, Cost 0 엣지, 미등록 노드 검사"""

import json
import math
import unittest
from pathlib import Path

from simulation.services.route_service import build_route_inputs, plan_route
from tests.fixtures import load_graph


class RoutePlannerServiceTest(unittest.TestCase):
    def setUp(self):
        self.graph = load_graph()

    # 최단 경로 알고리즘을 변경했을 때 올바른 방향성 경로를 선택하는지 확인한다.
    def test_chooses_shortest_directed_path(self):
        route = plan_route("1", "3", self.graph)
        self.assertEqual(route["node_ids"], ["1", "2", "3"])
        self.assertEqual(route["edge_ids"], ["e12", "e23"])
        self.assertEqual(route["cost"], 2)

    # cost 0 처리 방식을 변경했을 때 좌표 거리를 사용하는지 확인한다.
    def test_zero_cost_edge_uses_coordinate_distance(self):
        route = plan_route("1", "4", self.graph)
        self.assertEqual(route["node_ids"], ["1", "4"])
        self.assertAlmostEqual(route["cost"], math.sqrt(2))

    # LLM 평가 기준인 A* 알고리즘이 각 맵에서 최단 비용을 계산하는지 확인한다.
    def test_astar_minimum_stored_weight_on_both_maps(self):
        root = Path(__file__).resolve().parents[1] / "routes"
        for name in ("test.geojson", "test_int.geojson"):
            graph = json.loads((root / name).read_text(encoding="utf-8"))
            points, edges = build_route_inputs(graph, require_stored_weight=True)
            for start in points:
                distances = {node: math.inf for node in points}
                distances[start] = 0.0
                for _ in range(len(points) - 1):
                    changed = False
                    for a, b, weight in edges:
                        candidate = distances[a] + weight
                        if candidate < distances[b]:
                            distances[b] = candidate
                            changed = True
                    if not changed:
                        break
                for target, expected in distances.items():
                    if not math.isfinite(expected):
                        continue
                    with self.subTest(graph=name, start=start, target=target):
                        route = plan_route(
                            str(start), str(target), graph,
                            require_stored_weight=True,
                        )
                        self.assertAlmostEqual(route["cost"], expected)
                        self.assertEqual(route["node_ids"][0], str(start))
                        self.assertEqual(route["node_ids"][-1], str(target))

    # 방향성 엣지 처리를 변경했을 때 역방향 이동을 막는지 확인한다.
    def test_does_not_traverse_edge_in_reverse(self):
        with self.assertRaisesRegex(ValueError, "연결된 경로가 없습니다"):
            plan_route("3", "1", self.graph)

    # 노드 검증을 변경했을 때 등록되지 않은 노드를 거부하는지 확인한다.
    def test_unknown_node_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "존재하지 않는 경로 노드"):
            plan_route("1", "99", self.graph)


if __name__ == "__main__":
    unittest.main()
