"""모델 없이 V2 다음 노드 반복 선택과 실패 기록을 검증한다."""

import unittest

from simulation.evaluation.selector_iterative_route_benchmark import _run_route, _summarize


class _OracleSelector:
    """복수 후보 단계에서 정답 다음 노드를 반환한다."""

    name = "laya"
    model = "fake-oracle"

    def __init__(self):
        self.calls = 0
        self.states = []
        self.candidate_sets = []

    def select_choice(self, state, candidates, _instructions, *, question_id):
        self.calls += 1
        self.states.append(state)
        self.candidate_sets.append(dict(candidates))
        choice = {0: "node_1"}[state["current_node"]]
        if choice not in candidates:
            raise AssertionError(f"missing candidate: {choice}")
        return {
            "choice": choice,
            "confidence": 0.9,
            "answer_confidence": 0.9,
            "probabilities": {
                key: (0.9 if key == choice else 0.1) for key in candidates
            },
            "state_truncated": False,
            "usage": {"input_tokens": 120},
            "total_duration_seconds": 0.01,
            "eval_duration_seconds": 0.008,
            "runtime": {"device": "cuda:0"},
        }


class _InvalidEdgeSelector:
    """전체 노드 후보에서 실제 간선이 아닌 노드를 골라 검증 실패를 만든다."""

    name = "kev"
    model = "fake-invalid"

    def select_choice(self, _state, _candidates, _instructions, *, question_id):
        return {
            "choice": "node_3",
            "answer_confidence": 0.8,
            "probabilities": {"node_3": 0.8},
        }


def _fixture():
    return {
        "compact_graph": {
            "type": "CompactAdjacencyGraph",
            "directed": True,
            "nodes": [0, 1, 2],
            "adjacency": {
                "0": [
                    {"to": 1, "weight": 1.0},
                    {"to": 2, "weight": 3.0},
                ],
                "1": [{"to": 2, "weight": 1.0}],
                "2": [],
            },
        },
        "points": {0: (0.0, 0.0), 1: (1.0, 0.0), 2: (2.0, 0.0)},
        "edges": [(0, 1, 1.0), (0, 2, 3.0), (1, 2, 1.0)],
        "edge_weights": {(0, 1): 1.0, (0, 2): 3.0, (1, 2): 1.0},
        "nodes": [0, 1, 2],
    }


class SelectorIterativeRouteBenchmarkTest(unittest.TestCase):
    # 올바른 다음 노드를 두 번 고르면 최단 경로와 거리까지 일치해야 한다.
    def test_oracle_selector_reaches_exact_route(self):
        selector = _OracleSelector()
        result = _run_route(
            selector,
            _fixture(),
            {
                "start": 0,
                "target": 2,
                "expected_path": [0, 1, 2],
                "expected_distance": 2.0,
            },
            "neighbors",
            0.15,
        )

        self.assertIsNone(result["error"])
        self.assertEqual(result["path"], [0, 1, 2])
        self.assertTrue(result["exact_path_match"])
        self.assertTrue(result["distance_match"])
        self.assertEqual(result["api_call_count"], 1)
        self.assertEqual(selector.calls, 1)
        self.assertFalse(result["steps"][0]["forced_step"])
        self.assertTrue(result["steps"][1]["forced_step"])
        self.assertFalse(result["steps"][1]["model_called"])
        self.assertTrue(result["full_graph_input_preserved"])

    # 기본 모드는 available_edges의 Node만 Laya·Kev·Ollama choice 후보로 사용한다.
    def test_default_mode_builds_criteria_from_available_edges(self):
        selector = _OracleSelector()
        prepared = _fixture()
        prepared["nodes"].append(3)
        prepared["points"][3] = (3.0, 0.0)
        prepared["compact_graph"]["nodes"].append(3)
        prepared["compact_graph"]["adjacency"]["3"] = []

        result = _run_route(
            selector,
            prepared,
            {
                "start": 0,
                "target": 2,
                "expected_path": [0, 1, 2],
                "expected_distance": 2.0,
            },
            "neighbors",
            0.15,
        )

        self.assertIsNone(result["error"])
        self.assertEqual(
            selector.states[0]["available_edges"],
            [
                {"node": 1, "distance": 1.0},
                {"node": 2, "distance": 3.0},
            ],
        )
        self.assertEqual(
            selector.candidate_sets[0],
            {"node_1": "Node 1", "node_2": "Node 2"},
        )
        self.assertNotIn("node_3", selector.candidate_sets[0])

    # Context 모드는 criteria를 바꾸지 않고 available_edges만 추가해야 한다.
    def test_neighbor_context_changes_only_state_context(self):
        base_selector = _OracleSelector()
        context_selector = _OracleSelector()
        case = {
            "start": 0,
            "target": 2,
            "expected_path": [0, 1, 2],
            "expected_distance": 2.0,
        }

        base = _run_route(
            base_selector, _fixture(), case, "all", 0.15, "full_graph_only"
        )
        context = _run_route(
            context_selector, _fixture(), case, "all", 0.15, "neighbor_context"
        )

        self.assertNotIn("available_edges", base_selector.states[0])
        self.assertEqual(
            context_selector.states[0]["available_edges"],
            [
                {"node": 1, "distance": 1.0},
                {"node": 2, "distance": 3.0},
            ],
        )
        self.assertEqual(
            base["steps"][0]["candidates"],
            context["steps"][0]["candidates"],
        )
        self.assertEqual(base["context_mode"], "full_graph_only")
        self.assertEqual(context["context_mode"], "neighbor_context")

    # 직전 Node는 available_edges와 criteria에서 제외해 즉시 왕복을 막는다.
    def test_immediate_previous_node_is_not_a_candidate(self):
        selector = _OracleSelector()
        prepared = _fixture()
        prepared["compact_graph"]["adjacency"]["1"] = [
            {"to": 0, "weight": 1.0},
            {"to": 2, "weight": 1.0},
        ]
        prepared["edges"].append((1, 0, 1.0))
        prepared["edge_weights"][(1, 0)] = 1.0

        result = _run_route(
            selector,
            prepared,
            {
                "start": 0,
                "target": 2,
                "expected_path": [0, 1, 2],
                "expected_distance": 2.0,
            },
            "neighbors",
            0.15,
            "neighbor_context",
            max_steps=6,
        )

        self.assertIsNone(result["error"])
        self.assertEqual(result["path"], [0, 1, 2])
        self.assertEqual(result["steps"][1]["previous_node"], 0)
        self.assertEqual(result["steps"][1]["candidates"], {"node_2": "Node 2"})
        self.assertEqual(
            result["steps"][1]["available_edges"],
            [{"node": 2, "distance": 1.0}],
        )

    # 직전 Node가 아니면 과거 방문 Node로 돌아간 뒤 Target에 도착할 수 있다.
    def test_older_revisit_is_recorded_and_route_can_reach_target(self):
        class _ScriptedSelector:
            name = "kev"
            model = "fake-revisit"

            def __init__(self):
                self.choices = iter(["node_1", "node_0", "node_3"])

            def select_choice(self, _state, candidates, _instructions, *, question_id):
                choice = next(self.choices)
                if choice not in candidates:
                    raise AssertionError(f"missing candidate: {choice}")
                return {
                    "choice": choice,
                    "answer_confidence": 0.8,
                    "probabilities": {key: (0.8 if key == choice else 0.2) for key in candidates},
                }

        prepared = {
            "compact_graph": {
                "type": "CompactAdjacencyGraph",
                "directed": True,
                "nodes": [0, 1, 2, 3],
                "adjacency": {
                    "0": [{"to": 1, "weight": 1.0}, {"to": 3, "weight": 4.0}],
                    "1": [{"to": 0, "weight": 1.0}, {"to": 2, "weight": 1.0}],
                    "2": [{"to": 0, "weight": 1.0}, {"to": 3, "weight": 1.0}],
                    "3": [],
                },
            },
            "points": {0: (0.0, 0.0), 1: (1.0, 0.0), 2: (2.0, 0.0), 3: (3.0, 0.0)},
            "edges": [
                (0, 1, 1.0), (0, 3, 4.0), (1, 0, 1.0),
                (1, 2, 1.0), (2, 0, 1.0), (2, 3, 1.0),
            ],
            "edge_weights": {
                (0, 1): 1.0, (0, 3): 4.0, (1, 0): 1.0,
                (1, 2): 1.0, (2, 0): 1.0, (2, 3): 1.0,
            },
            "nodes": [0, 1, 2, 3],
        }

        result = _run_route(
            _ScriptedSelector(),
            prepared,
            {
                "start": 0,
                "target": 3,
                "expected_path": [0, 1, 2, 3],
                "expected_distance": 3.0,
            },
            "neighbors",
            0.15,
            "neighbor_context",
            max_steps=8,
        )

        self.assertIsNone(result["error"])
        self.assertEqual(result["path"], [0, 1, 2, 0, 3])
        self.assertTrue(result["valid_path"])
        self.assertEqual(result["revisit_count"], 1)
        self.assertTrue(result["steps"][2]["revisited"])

    # 3개 이상 Node의 순환은 허용하지만 max_steps에서 실패로 종료한다.
    def test_longer_cycle_stops_at_max_steps(self):
        class _MustNotRunSelector:
            name = "laya"

            def select_choice(self, *args, **kwargs):
                raise AssertionError("단일 후보 순환에서는 selector를 호출하면 안 됩니다.")

        prepared = {
            "compact_graph": {
                "type": "CompactAdjacencyGraph",
                "directed": True,
                "nodes": [0, 1, 2, 3],
                "adjacency": {
                    "0": [{"to": 1, "weight": 1.0}],
                    "1": [{"to": 2, "weight": 1.0}],
                    "2": [{"to": 0, "weight": 1.0}],
                    "3": [],
                },
            },
            "points": {0: (0.0, 0.0), 1: (1.0, 0.0), 2: (2.0, 0.0), 3: (3.0, 0.0)},
            "edges": [(0, 1, 1.0), (1, 2, 1.0), (2, 0, 1.0)],
            "edge_weights": {(0, 1): 1.0, (1, 2): 1.0, (2, 0): 1.0},
            "nodes": [0, 1, 2, 3],
        }

        result = _run_route(
            _MustNotRunSelector(),
            prepared,
            {
                "start": 0,
                "target": 3,
                "expected_path": [0, 1, 2, 3],
                "expected_distance": 3.0,
            },
            "neighbors",
            0.15,
            "neighbor_context",
            max_steps=4,
        )

        self.assertEqual(result["path"], [0, 1, 2, 0, 1])
        self.assertEqual(result["revisit_count"], 2)
        self.assertIn("최대 단계 초과: max_steps=4", result["error"])

    # 전체 노드 모드에서 없는 간선을 고르면 첫 실패 단계와 원인을 남겨야 한다.
    def test_invalid_edge_choice_is_recorded(self):
        prepared = _fixture()
        prepared["nodes"].append(3)
        prepared["points"][3] = (3.0, 0.0)
        prepared["compact_graph"]["nodes"].append(3)
        prepared["compact_graph"]["adjacency"]["3"] = []
        result = _run_route(
            _InvalidEdgeSelector(),
            prepared,
            {
                "start": 0,
                "target": 2,
                "expected_path": [0, 1, 2],
                "expected_distance": 2.0,
            },
            "all",
            0.15,
        )
        summary = _summarize([{"selector_name": "kev", **result}])

        self.assertEqual(result["failed_step"], 1)
        self.assertEqual(result["invalid_edge_count"], 1)
        self.assertFalse(result["steps"][0]["accepted"])
        self.assertIn("존재하지 않는 방향성 edge", result["error"])
        self.assertEqual(summary["state_truncation_unreported_trial_count"], 0)

    # 단일 후보는 모델 오류로 처리하지 않고 API 호출 없는 강제 이동으로 기록한다.
    def test_single_candidate_is_forced_without_selector_call(self):
        class _MustNotRunSelector:
            name = "laya"

            def select_choice(self, *args, **kwargs):
                raise AssertionError("단일 후보에서 selector를 호출하면 안 됩니다.")

        prepared = _fixture()
        prepared["compact_graph"]["adjacency"]["0"] = [
            {"to": 1, "weight": 1.0}
        ]
        prepared["edges"] = [(0, 1, 1.0), (1, 2, 1.0)]
        prepared["edge_weights"] = {(0, 1): 1.0, (1, 2): 1.0}
        result = _run_route(
            _MustNotRunSelector(),
            prepared,
            {
                "start": 0,
                "target": 2,
                "expected_path": [0, 1, 2],
                "expected_distance": 2.0,
            },
            "neighbors",
            0.15,
        )
        summary = _summarize([{"selector_name": "laya", **result}])

        self.assertIsNone(result["error"])
        self.assertEqual(result["api_call_count"], 0)
        self.assertEqual(summary["forced_step_count"], 2)
        self.assertEqual(summary["model_decision_step_count"], 0)
        self.assertEqual(summary["state_truncation_unreported_trial_count"], 0)
        self.assertIsNone(summary["step_realtime_met_rate"])
        self.assertTrue(all(step["forced_step"] for step in result["steps"]))


if __name__ == "__main__":
    unittest.main()
