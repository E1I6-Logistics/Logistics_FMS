"""V2와 최종 시험이 같은 인접 후보·순환 제한·강제 이동을 사용하는지 확인한다."""
import unittest
from simulation.evaluation.iterative_chain import IterativeRouteError, run_iterative_chain
from simulation.services.iterative_route_runner import run_selected_route
from simulation.evaluation.selector_iterative_route_benchmark import _run_route

GRAPH = {
    "type": "CompactAdjacencyGraph", "nodes": [1, 2, 3, 4],
    "adjacency": {
        "1": [{"to": 2, "weight": 1}, {"to": 4, "weight": 5}],
        "2": [{"to": 3, "weight": 1}], "3": [],
        "4": [{"to": 3, "weight": 5}],
    },
}

class FakeProvider:
    model = "fake"
    def __init__(self, actions):
        self.actions = list(actions)
        self.last_inference = None
        self.payloads = []
        self.schemas = []

    def request_structured(self, **kwargs):
        self.payloads.append(kwargs["payload"])
        self.schemas.append(kwargs["output_schema"])
        action = self.actions.pop(0)
        if isinstance(action, Exception):
            raise action
        self.last_inference = {
            "request": {"messages": [{"content": str(kwargs["payload"])}]},
            "diagnostics": {"eval_count": 1},
        }
        return action

class IterativeChainTest(unittest.TestCase):
    # 최종 시험의 실행 함수를 공유해 두 구현의 규칙이 따로 달라지지 않게 한다.
    def test_final_benchmark_uses_same_runner(self):
        self.assertIs(_run_route, run_selected_route)

    # 인접 후보를 enum으로 제한하고 유일한 다음 노드는 호출 없이 이동한다.
    def test_neighbor_choice_and_forced_step(self):
        provider = FakeProvider([{"choice": "node_2"}])
        result = run_iterative_chain(provider, GRAPH, 1, 3, instructions="test", max_steps=8)
        self.assertEqual(result["path"], [1, 2, 3])
        self.assertEqual(result["reported_total_distance"], 2)
        self.assertEqual(result["api_call_count"], 1)
        self.assertTrue(result["chain_steps"][1]["forced_step"])
        self.assertEqual(provider.schemas[0]["properties"]["choice"]["enum"], ["node_2", "node_4"])
        self.assertNotIn("available_edges", provider.payloads[0]["state"])

    # 두 Context 조건은 동일 Graph·후보를 쓰며 추가 인접 정보 유무만 다르다.
    def test_context_changes_only_available_edges(self):
        providers = [FakeProvider([{"choice": "node_2"}]) for _ in range(2)]
        for enabled, provider in zip((False, True), providers):
            run_iterative_chain(provider, GRAPH, 1, 3, instructions="test", max_steps=8,
                                neighbor_context_enabled=enabled)
        plain, context = [p.payloads[0] for p in providers]
        self.assertEqual(context["state"].pop("available_edges"),
                         [{"node": 2, "weight": 1}, {"node": 4, "weight": 5}])
        self.assertEqual(plain, context)
        self.assertEqual(plain["state"]["route_graph"], GRAPH)
        self.assertEqual(plain["state"]["max_visits_per_node"], 2)

    # 후보 밖 응답은 실패 단계와 부분 경로를 남기며 유효 도착으로 세지 않는다.
    def test_invalid_choice_retains_failed_step(self):
        provider = FakeProvider([{"choice": "node_3"}])
        with self.assertRaises(IterativeRouteError) as caught:
            run_iterative_chain(provider, GRAPH, 1, 3, instructions="test", max_steps=8)
        answer = caught.exception.route_answer
        self.assertEqual(answer["path"], [1])
        self.assertEqual(answer["api_call_count"], 1)
        self.assertFalse(answer["chain_steps"][0]["accepted"])

    # 선택지가 하나인 전체 경로는 모델 호출 0회와 강제 이동으로 기록한다.
    def test_forced_only_route_has_zero_calls(self):
        graph = {"type": "CompactAdjacencyGraph", "nodes": [1, 2], "adjacency": {"1": [{"to": 2, "weight": 1.5}], "2": []}}
        provider = FakeProvider([])
        answer = run_iterative_chain(provider, graph, 1, 2, instructions="test", max_steps=4)
        self.assertEqual(answer["api_call_count"], 0)
        self.assertEqual(answer["request_character_count"], 0)
        self.assertEqual(provider.payloads, [])

    # HTTP 진단이 없는 연결 실패도 시도한 호출 1회와 실패 단계를 보존한다.
    def test_transport_failure_keeps_attempt_count(self):
        provider = FakeProvider([TimeoutError("timed out")])
        with self.assertRaises(IterativeRouteError):
            run_iterative_chain(provider, GRAPH, 1, 3, instructions="test", max_steps=8)
        self.assertEqual(provider.last_chain_result["api_call_count"], 1)
        self.assertEqual(provider.last_chain_inferences, [])
        self.assertFalse(provider.last_chain_steps[0]["accepted"])

    # benchmark 집계에서도 강제 이동을 API 1회로 오인하지 않는지 확인한다.
    def test_trial_counts_zero_calls_for_forced_route(self):
        from simulation.evaluation.benchmark import _run_trial
        graph = {"type": "CompactAdjacencyGraph", "nodes": [1, 2],
                 "adjacency": {"1": [{"to": 2, "weight": 1.5}], "2": []}}
        prepared = self._trial_inputs(graph)
        case = {"start": 1, "goal": 2, "expected_path": [1, 2], "expected_distance": 1.5}
        trial = _run_trial(FakeProvider([]), "fake", case, 1, prepared)
        self.assertTrue(trial["metrics"]["valid_path"])
        self.assertEqual(trial["metrics"]["api_call_count"], 0)
        self.assertEqual(trial["metrics"]["forced_step_count"], 1)
        self.assertEqual(trial["metrics"]["input_character_count"], 0)

    # 서버 실패는 부분 경로·timeout·실제 호출 수로 남아 모델 정답과 섞이지 않는다.
    def test_trial_retains_transport_failure(self):
        from simulation.evaluation.benchmark import _run_trial
        case = {"start": 1, "goal": 3, "expected_path": [1, 2, 3], "expected_distance": 2}
        trial = _run_trial(FakeProvider([TimeoutError("timed out")]), "fake", case, 1,
                           self._trial_inputs(GRAPH))
        self.assertFalse(trial["metrics"]["valid_path"])
        self.assertTrue(trial["metrics"]["timed_out"])
        self.assertEqual(trial["metrics"]["api_call_count"], 1)
        self.assertEqual(trial["llm"]["path"], [1])
        self.assertFalse(trial["llm"]["chain_steps"][0]["accepted"])

    @staticmethod
    def _trial_inputs(graph):
        from simulation.services.route_service import compact_graph_edges
        from pathlib import Path
        return {"config": {"prompt": "test", "settings": {
                    "execution_strategy": "iterative_chain", "max_chain_steps": 8,
                    "max_attempts": 1, "realtime_deadline_seconds": 0.15}},
                "compact_graph": graph, "points": {n: None for n in graph["nodes"]},
                "edges": [(e["from"], e["to"], e["weight"]) for e in compact_graph_edges(graph)],
                "graph_path": Path("fake.geojson"), "graph_sha256": "fake"}

    # 도착 전에 이동 상한에 도달하면 부분 경로를 남기고 종료한다.
    def test_max_steps_stops_partial_route(self):
        with self.assertRaisesRegex(IterativeRouteError, "최대 단계 초과") as caught:
            run_iterative_chain(FakeProvider([{"choice": "node_2"}]), GRAPH, 1, 3,
                                instructions="test", max_steps=1)
        self.assertEqual(caught.exception.route_answer["path"], [1, 2])

if __name__ == "__main__":
    unittest.main()
