"""LLM 실행 기록이 누적 평가 지표로 정확히 변환되는지 검사한다."""

import unittest

from simulation.summarize_llm_comparisons import summarize


class LlmComparisonSummaryTest(unittest.TestCase):
    def test_rates_and_means_are_grouped_by_model_and_prompt(self):
        """성공 1건과 실패 1건을 같은 실험 그룹으로 집계한다."""
        # 두 실행이 동일 그룹으로 묶이도록 provider, model, prompt, graph를
        # 공통 조건으로 사용한다.
        common = {
            "provider": "ollama",
            "model": "fixture-model",
            "prompt_strategy": "compact-dijkstra",
            "input": {"route_graph_file": "test_compact_graph.geojson"},
        }
        records = [
            # 첫 번째 실행: JSON과 경로가 모두 유효하고 비교도 성공한 경우.
            {
                **common,
                "metrics": {
                    "json_response_success": True,
                    "valid_path": True,
                    "shortest_path_match": True,
                    "shortest_distance_match": True,
                    "absolute_distance_error": 0.0,
                    "response_time_seconds": 1.0,
                    "realtime_deadline_seconds": 0.15,
                    "meets_realtime_deadline": True,
                    "timed_out": False,
                    "first_attempt_success": True,
                    "retry_success": False,
                    "input_character_count": 100,
                    "estimated_input_tokens": 25,
                },
            },
            # 두 번째 실행: 응답이 제한 시간을 넘겨 경로를 얻지 못한 경우.
            {
                **common,
                "metrics": {
                    "json_response_success": False,
                    "valid_path": False,
                    "shortest_path_match": False,
                    "shortest_distance_match": False,
                    "absolute_distance_error": None,
                    "response_time_seconds": 3.0,
                    "realtime_deadline_seconds": 0.15,
                    "meets_realtime_deadline": False,
                    "timed_out": True,
                    "first_attempt_success": False,
                    "retry_success": False,
                    "input_character_count": 100,
                    "estimated_input_tokens": 25,
                },
            },
        ]

        # 그룹 조건이 같으므로 결과 배열에는 하나의 집계 그룹만 만들어진다.
        group = summarize(records)["groups"][0]

        # 성공 1건, 실패 1건이므로 비율은 0.5이고 평균 응답 시간은 2초다.
        self.assertEqual(group["run_count"], 2)
        self.assertEqual(group["valid_path_rate"], 0.5)
        self.assertEqual(group["timeout_rate"], 0.5)
        self.assertEqual(group["mean_response_time_seconds"], 2.0)
        self.assertEqual(group["realtime_deadline_seconds"], 0.15)
        self.assertEqual(group["realtime_deadline_success_rate"], 0.5)
        # 거리 오차가 없는 실패 기록은 평균에서 제외되므로 성공 기록의 0만 남는다.
        self.assertEqual(group["mean_absolute_distance_error"], 0.0)


if __name__ == "__main__":
    unittest.main()
