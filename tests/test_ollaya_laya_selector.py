"""실제 Ollaya 서버 없이 Laya selector의 요청과 응답 처리를 검증한다."""

from __future__ import annotations

import unittest

from simulation.route_selector.ollaya_laya_selector import OllayaLayaSelector


class OllayaLayaSelectorTest(unittest.TestCase):
    def setUp(self):
        self.calls = []

    def transport(self, url, payload, headers, timeout):
        self.calls.append((url, payload, headers, timeout))
        return {
            "model": "laya:multilingual",
            "answers": {
                "route": {
                    "type": "choice",
                    "choice": "route_b",
                    "confidence": 0.82,
                    "probabilities": {"route_a": 0.18, "route_b": 0.82},
                }
            },
            "routing": {"route": "multilingual"},
            "total_duration": 20_000_000,
            "load_duration": 2_000_000,
            "eval_duration": 15_000_000,
        }

    def test_sends_route_choice_question_and_parses_native_timings(self):
        selector = OllayaLayaSelector(
            model="laya",
            host="http://ollaya.test:11435/",
            timeout_seconds=3,
            api_key="secret",
            transport=self.transport,
        )
        result = selector.select_route(
            {"start_node": 2, "target_node": 10},
            {
                "route_a": "path=[2,5,4,6,13,8,9,10], distance=3.033652",
                "route_b": "path=[2,5,4,6,10], distance=1.592143",
            },
        )

        self.assertEqual(result["choice"], "route_b")
        self.assertEqual(result["model"], "laya:multilingual")
        self.assertAlmostEqual(result["total_duration_seconds"], 0.02)
        self.assertAlmostEqual(result["eval_duration_seconds"], 0.015)
        url, payload, headers, timeout = self.calls[0]
        self.assertEqual(url, "http://ollaya.test:11435/api/decide")
        self.assertEqual(payload["model"], "laya")
        self.assertEqual(payload["questions"]["route"]["type"], "choice")
        self.assertEqual(headers["Authorization"], "Bearer secret")
        self.assertEqual(timeout, 3)
        self.assertEqual(selector.last_inference["response"]["model"], "laya:multilingual")

    def test_select_choice_supports_non_route_questions(self):
        def reasoning_transport(_url, payload, _headers, _timeout):
            self.assertIn("reasoning", payload["questions"])
            self.assertEqual(
                payload["questions"]["reasoning"]["instructions"],
                "가장 큰 사람을 선택하세요.",
            )
            return {
                "model": "laya:multilingual",
                "answers": {
                    "reasoning": {
                        "choice": "minsu",
                        "confidence": 0.75,
                        "probabilities": {"minsu": 0.75, "younghee": 0.25},
                    }
                },
            }

        selector = OllayaLayaSelector(transport=reasoning_transport)
        result = selector.select_choice(
            "민수는 영희보다 큽니다.",
            {"minsu": "민수", "younghee": "영희"},
            "가장 큰 사람을 선택하세요.",
            question_id="reasoning",
        )

        self.assertEqual(result["choice"], "minsu")
        self.assertEqual(result["confidence"], 0.75)

    def test_rejects_unknown_choice(self):
        def invalid_transport(*_args):
            return {"answers": {"route": {"choice": "route_x"}}}

        selector = OllayaLayaSelector(transport=invalid_transport)
        with self.assertRaisesRegex(RuntimeError, "알 수 없는 후보"):
            selector.select_route("state", {"route_a": "A", "route_b": "B"})

    def test_requires_at_least_two_candidates(self):
        selector = OllayaLayaSelector(transport=self.transport)
        with self.assertRaisesRegex(ValueError, "두 개 이상"):
            selector.select_route("state", {"route_a": "A"})


if __name__ == "__main__":
    unittest.main()
