"""Iterative Chain에서 모델 선택과 Python 검증의 경계를 확인한다."""

import unittest

from simulation.evaluation.iterative_chain import run_iterative_chain


GRAPH = {
    "type": "CompactRouteGraph",
    "nodes": [1, 2, 3],
    "edges": [
        {"from": 1, "to": 2, "weight": 1.0},
        {"from": 1, "to": 3, "weight": 5.0},
        {"from": 2, "to": 3, "weight": 1.0},
    ],
}


class FakeProvider:
    def __init__(self, actions):
        self.actions = list(actions)
        self.last_inference = None

    def request_structured(self, **kwargs):
        self.last_inference = {
            "request": {"messages": [{"content": str(kwargs["payload"])}]},
            "diagnostics": {"eval_count": 1},
        }
        return self.actions.pop(0)


class IterativeChainTest(unittest.TestCase):
    # 모델이 고른 정상 Dijkstra 단계가 이어져 최종 경로로 복원되는지 확인한다.
    def test_uses_model_selected_steps(self):
        provider = FakeProvider(
            [
                {
                    "selected_node": 1,
                    "selected_distance": 0.0,
                    "relaxations": [
                        {"node": 2, "distance": 1.0, "predecessor": 1},
                        {"node": 3, "distance": 5.0, "predecessor": 1},
                    ],
                    "finished": False,
                },
                {
                    "selected_node": 2,
                    "selected_distance": 1.0,
                    "relaxations": [
                        {"node": 3, "distance": 2.0, "predecessor": 2},
                    ],
                    "finished": False,
                },
                {
                    "selected_node": 3,
                    "selected_distance": 2.0,
                    "relaxations": [],
                    "finished": True,
                },
            ]
        )

        result = run_iterative_chain(
            provider, GRAPH, 1, 3, instructions="test", max_steps=3
        )

        self.assertEqual(result["path"], [1, 2, 3])
        self.assertEqual(result["reported_total_distance"], 2.0)
        self.assertEqual(result["api_call_count"], 3)

    # 모델이 최소 tentative distance가 아닌 노드를 선택하면 대신 고치지 않고 실패한다.
    def test_rejects_nonminimum_model_choice(self):
        provider = FakeProvider(
            [
                {
                    "selected_node": 3,
                    "selected_distance": 5.0,
                    "relaxations": [],
                    "finished": True,
                }
            ]
        )

        with self.assertRaisesRegex(ValueError, "선택할 수 없는 노드"):
            run_iterative_chain(
                provider, GRAPH, 1, 3, instructions="test", max_steps=3
            )

    # 모델이 존재하지 않거나 개선 대상이 아닌 Edge를 만들면 응답 검증에서 거부한다.
    def test_rejects_invalid_relaxation(self):
        provider = FakeProvider(
            [
                {
                    "selected_node": 1,
                    "selected_distance": 0.0,
                    "relaxations": [
                        {"node": 2, "distance": 1.0, "predecessor": 1},
                        {"node": 99, "distance": 1.0, "predecessor": 1},
                    ],
                    "finished": False,
                }
            ]
        )

        with self.assertRaisesRegex(ValueError, "relaxation 대상"):
            run_iterative_chain(
                provider, GRAPH, 1, 3, instructions="test", max_steps=3
            )


if __name__ == "__main__":
    unittest.main()
