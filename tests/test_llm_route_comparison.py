"""실제 LLM 대신 mock 응답을 넣어 비교·저장 흐름 검사"""

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from simulation import llm_route_comparison
from tests.fixtures import MOCK_DIR, load_graph, load_responses, route_inputs


class LlmRouteComparisonTest(unittest.TestCase):
    def setUp(self):
        self.points, self.edges = route_inputs()
        self.responses = load_responses()
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.result_path = Path(self.temporary_directory.name) / "comparisons.jsonl"

    def test_mocked_provider_result_is_compared_and_saved(self):
        with (
            patch.object(llm_route_comparison, "ROUTE_GRAPH_PATH", MOCK_DIR / "route_graph.geojson"),
            patch.object(llm_route_comparison, "LLM_RESULT_PATH", self.result_path),
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
        self.assertEqual(json.loads(self.result_path.read_text(encoding="utf-8")), result)

    def test_invalid_model_path_is_not_recorded(self):
        with (
            patch.object(llm_route_comparison, "ROUTE_GRAPH_PATH", MOCK_DIR / "route_graph.geojson"),
            patch.object(llm_route_comparison, "LLM_RESULT_PATH", self.result_path),
            patch.object(
                llm_route_comparison,
                "request_llm_shortest_path",
                return_value=self.responses["nonexistent_edge"],
            ),
        ):
            with self.assertRaisesRegex(ValueError, "존재하지 않는 방향성 edge"):
                llm_route_comparison.compare_path_with_llm(
                    self.points, self.edges, 1, 3, [1, 2, 3]
                )
        self.assertFalse(self.result_path.exists())


if __name__ == "__main__":
    unittest.main()
