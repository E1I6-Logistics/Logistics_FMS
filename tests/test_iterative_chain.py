"""Iterative next-node 입력, 이동과 Edge 검증을 확인한다."""

import unittest

from simulation.evaluation.iterative_chain import run_iterative_chain


GRAPH = {
    "type": "CompactAdjacencyGraph",
    "nodes": [1, 2, 3, 4],
    "adjacency": {
        "1": [{"to": 2, "weight": 1.0}, {"to": 4, "weight": 5.0}],
        "2": [{"to": 3, "weight": 1.0}],
        "3": [],
        "4": [{"to": 3, "weight": 5.0}],
    },
}


class FakeProvider:
    def __init__(self, actions):
        self.actions = list(actions)
        self.last_inference = None
        self.payloads = []

    def request_structured(self, **kwargs):
        self.payloads.append(kwargs["payload"])
        self.last_inference = {
            "request": {"messages": [{"content": str(kwargs["payload"])}]},
            "diagnostics": {"eval_count": 1},
        }
        return self.actions.pop(0)


class IterativeChainTest(unittest.TestCase):
    # 매 단계 모델 선택을 실제 Edge로 이동시켜 Target까지 도착하는지 확인한다.
    def test_reaches_target_with_one_model_call_per_step(self):
        provider = FakeProvider(
            [{"selected_node": 2}, {"selected_node": 3}]
        )

        result = run_iterative_chain(
            provider, GRAPH, 1, 3, instructions="test", max_steps=3
        )

        self.assertEqual(result["path"], [1, 2, 3])
        self.assertEqual(result["reported_total_distance"], 2.0)
        self.assertEqual(result["api_call_count"], 2)
        self.assertNotIn("criteria", provider.payloads[0])
        self.assertNotIn("available_edges", provider.payloads[0])

    # Neighbor Context가 전체 Graph를 유지하며 정확 조회한 Edge만 추가하는지 확인한다.
    def test_neighbor_context_adds_exact_edges_without_replacing_full_graph(self):
        provider = FakeProvider(
            [{"selected_node": 2}, {"selected_node": 3}]
        )

        run_iterative_chain(
            provider,
            GRAPH,
            1,
            3,
            instructions="test",
            max_steps=3,
            neighbor_context_enabled=True,
        )

        first = provider.payloads[0]
        second = provider.payloads[1]
        self.assertEqual(first["route_graph"], GRAPH)
        self.assertEqual(
            first["available_edges"],
            [
                {"node": 2, "weight": 1},
                {"node": 4, "weight": 5},
            ],
        )
        self.assertEqual(
            second["available_edges"],
            [{"node": 3, "weight": 1}],
        )
        self.assertNotIn("criteria", first)

    # 현재 Node와 직접 연결되지 않은 반환값은 실행 전에 거부하는지 확인한다.
    def test_rejects_non_neighbor_choice(self):
        provider = FakeProvider([{"selected_node": 3}])

        with self.assertRaisesRegex(ValueError, "존재하지 않는 방향성 edge"):
            run_iterative_chain(
                provider, GRAPH, 1, 3, instructions="test", max_steps=3
            )

    # 선택지가 하나인 단계도 모델을 호출해 selected_node를 받는지 확인한다.
    def test_single_connection_still_calls_model(self):
        graph = {
            "type": "CompactAdjacencyGraph",
            "nodes": [1, 2],
            "adjacency": {"1": [{"to": 2, "weight": 1.5}], "2": []},
        }
        provider = FakeProvider([{"selected_node": 2}])

        result = run_iterative_chain(
            provider, graph, 1, 2, instructions="test", max_steps=1
        )

        self.assertEqual(result["path"], [1, 2])
        self.assertEqual(result["api_call_count"], 1)


if __name__ == "__main__":
    unittest.main()
