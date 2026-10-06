"""Graph Retrieval이 정답을 계산하지 않고 관련 연결 정보만 반환하는지 확인한다."""

import unittest

from simulation.evaluation.graph_retrieval import (
    ground_truth_coverage,
    retrieve_path_relevant_graph,
)


class GraphRetrievalTest(unittest.TestCase):
    # Start에서 갈 수 있어도 Target으로 이어지지 않는 dead-end는 제외한다.
    def test_retrieves_nodes_on_any_possible_start_target_route(self):
        graph = {
            "type": "CompactRouteGraph",
            "nodes": [1, 2, 3, 4],
            "edges": [
                {"from": 1, "to": 2, "weight": 1.0},
                {"from": 2, "to": 3, "weight": 2.0},
                {"from": 1, "to": 4, "weight": 0.5},
            ],
        }

        retrieved, metadata = retrieve_path_relevant_graph(graph, 1, 3)

        self.assertEqual(retrieved["nodes"], [1, 2, 3])
        self.assertEqual(len(retrieved["edges"]), 2)
        self.assertNotIn("path", retrieved)
        self.assertEqual(metadata["retrieved_node_count"], 3)

    # Retrieval 결과의 인접 Node와 저장 거리 정보가 모델 입력에 포함되는지 확인한다.
    def test_includes_adjacency_distances_and_ground_truth_coverage(self):
        graph = {
            "type": "CompactRouteGraph",
            "nodes": [1, 2, 3],
            "edges": [
                {"from": 1, "to": 2, "weight": 1.25},
                {"from": 2, "to": 3, "weight": 2.5},
            ],
        }

        retrieved, _ = retrieve_path_relevant_graph(graph, 1, 3)
        coverage = ground_truth_coverage(retrieved, [1, 2, 3])

        self.assertEqual(
            retrieved["adjacency"][0],
            {"node": 1, "neighbors": [{"node": 2, "distance": 1.25}]},
        )
        self.assertTrue(coverage["ground_truth_path_available"])
        self.assertEqual(coverage["ground_truth_edge_recall"], 1.0)

    # V2 adjacency 입력은 Retrieval 뒤에도 edges 중복 없이 같은 형식을 유지한다.
    def test_preserves_v2_compact_adjacency_format(self):
        graph = {
            "type": "CompactAdjacencyGraph",
            "nodes": [1, 2, 3, 4],
            "adjacency": {
                "1": [{"to": 2, "weight": 1.0}, {"to": 4, "weight": 0.5}],
                "2": [{"to": 3, "weight": 2.0}],
                "3": [],
                "4": [],
            },
        }

        retrieved, metadata = retrieve_path_relevant_graph(graph, 1, 3)

        self.assertEqual(retrieved["type"], "CompactAdjacencyGraph")
        self.assertEqual(retrieved["nodes"], [1, 2, 3])
        self.assertNotIn("edges", retrieved)
        self.assertEqual(retrieved["adjacency"]["1"], [{"to": 2, "weight": 1.0}])
        self.assertEqual(metadata["retrieved_edge_count"], 2)


if __name__ == "__main__":
    unittest.main()
