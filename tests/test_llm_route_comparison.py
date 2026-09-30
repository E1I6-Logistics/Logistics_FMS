"""실제 LLM 대신 mock 응답을 넣어 비교·저장 흐름 검사"""

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from simulation.evaluation import comparison as llm_route_comparison
from tests.fixtures import MOCK_DIR, load_graph, load_responses, route_inputs


class LlmRouteComparisonTest(unittest.TestCase):
    def setUp(self):
        self.points, self.edges = route_inputs()
        self.responses = load_responses()
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.result_path = Path(self.temporary_directory.name) / "comparisons.jsonl"
        self.summary_path = Path(self.temporary_directory.name) / "summary.json"

    # LLM 비교·저장 흐름을 변경했을 때 성공 결과와 지표가 기록되는지 확인한다.
    def test_mocked_provider_result_is_compared_and_saved(self):
        with (
            patch.object(llm_route_comparison, "ROUTE_GRAPH_PATH", MOCK_DIR / "route_graph.geojson"),
            patch.object(llm_route_comparison, "LLM_RESULT_PATH", self.result_path),
            patch.object(llm_route_comparison, "LLM_SUMMARY_PATH", self.summary_path),
            patch.object(
                llm_route_comparison,
                "request_llm_shortest_path",
                return_value=self.responses["alternative"],
            ) as request,
            patch.dict(os.environ, {"LLM_PROVIDER": "ollama", "OLLAMA_MODEL": "fixture-model"}),
        ):
            result = llm_route_comparison.compare_path_with_llm(
                self.points, self.edges, 1, 3, [1, 2, 3]
            )

        request.assert_called_once_with(load_graph(), 1, 3)
        self.assertEqual(result["provider"], "ollama")
        self.assertEqual(result["model"], "fixture-model")
        self.assertEqual(result["llm"]["recalculated_total_distance"], 3)
        self.assertFalse(result["comparison"]["same_distance"])
        self.assertTrue(result["metrics"]["json_response_success"])
        self.assertTrue(result["metrics"]["valid_path"])
        self.assertTrue(result["metrics"]["first_attempt_success"])
        self.assertEqual(result["metrics"]["realtime_deadline_seconds"], 0.15)
        self.assertTrue(result["metrics"]["meets_realtime_deadline"])
        self.assertGreater(result["metrics"]["input_character_count"], 0)
        self.assertEqual(json.loads(self.result_path.read_text(encoding="utf-8")), result)
        self.assertEqual(
            json.loads(self.summary_path.read_text(encoding="utf-8"))["total_run_count"],
            1,
        )

    # 실패 기록 방식을 변경했을 때 유효하지 않은 모델 경로가 실패로 남는지 확인한다.
    def test_invalid_model_path_is_recorded_as_failure(self):
        with (
            patch.object(llm_route_comparison, "ROUTE_GRAPH_PATH", MOCK_DIR / "route_graph.geojson"),
            patch.object(llm_route_comparison, "LLM_RESULT_PATH", self.result_path),
            patch.object(llm_route_comparison, "LLM_SUMMARY_PATH", self.summary_path),
            patch.object(
                llm_route_comparison,
                "request_llm_shortest_path",
                return_value=self.responses["nonexistent_edge"],
            ),
        ):
            result = llm_route_comparison.compare_path_with_llm(
                self.points, self.edges, 1, 3, [1, 2, 3]
            )

        self.assertEqual(result["status"], "failed")
        self.assertFalse(result["metrics"]["valid_path"])
        self.assertFalse(result["metrics"]["meets_realtime_deadline"])
        self.assertEqual(result["error"]["type"], "ValueError")
        self.assertTrue(self.result_path.exists())

    # 재시도 로직을 변경했을 때 두 번째 성공이 구분되어 기록되는지 확인한다.
    def test_retry_success_is_recorded(self):
        with (
            patch.object(llm_route_comparison, "ROUTE_GRAPH_PATH", MOCK_DIR / "route_graph.geojson"),
            patch.object(llm_route_comparison, "LLM_RESULT_PATH", self.result_path),
            patch.object(llm_route_comparison, "LLM_SUMMARY_PATH", self.summary_path),
            patch.object(
                llm_route_comparison,
                "request_llm_shortest_path",
                side_effect=[
                    self.responses["nonexistent_edge"],
                    self.responses["matching"],
                ],
            ),
        ):
            result = llm_route_comparison.compare_path_with_llm(
                self.points,
                self.edges,
                1,
                3,
                [1, 2, 3],
                max_attempts=2,
            )

        self.assertEqual(result["status"], "success")
        self.assertEqual(result["metrics"]["attempt_count"], 2)
        self.assertFalse(result["metrics"]["first_attempt_success"])
        self.assertTrue(result["metrics"]["retry_success"])


if __name__ == "__main__":
    unittest.main()
