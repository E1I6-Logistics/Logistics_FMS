"""실제 Kev 서버 없이 API 요청과 CUDA 검증을 테스트한다."""

from __future__ import annotations

import unittest

from simulation.route_selector.kev_selector import KevSelector


class KevSelectorTest(unittest.TestCase):
    def setUp(self):
        self.posts = []
        self.gets = []

    def metadata(self, url, headers, timeout):
        self.gets.append((url, headers, timeout))
        return {
            "models": [
                {
                    "name": "kev-latest",
                    "run": "jaredpalmer/kev-0.8b",
                    "device": "cuda",
                    "backend": "torch",
                    "dtype": "bfloat16",
                }
            ]
        }

    def post(self, url, payload, headers, timeout):
        self.posts.append((url, payload, headers, timeout))
        question_id, question = next(iter(payload["questions"].items()))
        if question["type"] == "choice":
            answer = {
                "type": "choice",
                "choice": "route_b",
                "confidence": 0.82,
                "probabilities": {"route_a": 0.18, "route_b": 0.82},
            }
        elif question["type"] == "score":
            answer = {
                "type": "score",
                "score": 3.8,
                "confidence": 0.9,
                "legend": {"0": "low", "4": "high"},
                "probabilities": {"0": 0.01, "4": 0.91},
            }
        else:
            answer = {"type": "noul", "noul": 0.95}
        return {
            "model": "kev-latest",
            "answers": {question_id: answer},
            "usage": {"input_tokens": 32, "output_tokens": 1},
            "latency_ms": 25.0,
        }

    def selector(self, **kwargs):
        return KevSelector(
            host="http://kev.test:8009/",
            api_key="secret",
            transport=self.post,
            metadata_transport=self.metadata,
            **kwargs,
        )

    def test_checks_cuda_once_and_selects_route(self):
        selector = self.selector(require_cuda=True)
        candidates = {"route_a": "long", "route_b": "short"}
        first = selector.select_route("state", candidates)
        second = selector.select_route("state", candidates)

        self.assertEqual(len(self.gets), 1)
        self.assertEqual(len(self.posts), 2)
        self.assertEqual(self.gets[0][0], "http://kev.test:8009/v1/models")
        self.assertEqual(self.posts[0][0], "http://kev.test:8009/v1/systemone")
        self.assertEqual(self.posts[0][2]["Authorization"], "Bearer secret")
        self.assertEqual(first["choice"], "route_b")
        self.assertEqual(second["runtime"]["device"], "cuda")
        self.assertEqual(first["eval_duration_seconds"], 0.025)

    def test_supports_score_and_noul(self):
        selector = self.selector(require_cuda=True)
        score = selector.evaluate_score(
            "state", ["a", "b", "c", "d", "e"], "rate"
        )
        noul = selector.evaluate_noul("state", "is stopped")
        self.assertEqual(score["score"], 3.8)
        self.assertEqual(noul["noul"], 0.95)

    def test_rejects_cpu_server_when_cuda_is_required(self):
        def cpu_metadata(_url, _headers, _timeout):
            return {"models": [{"name": "kev-latest", "device": "cpu"}]}

        selector = KevSelector(
            transport=self.post,
            metadata_transport=cpu_metadata,
            require_cuda=True,
        )
        with self.assertRaisesRegex(RuntimeError, "CUDA에서 실행되지 않습니다"):
            selector.select_route("state", {"route_a": "A", "route_b": "B"})

    def test_rejects_unknown_choice(self):
        def invalid_post(_url, payload, _headers, _timeout):
            question_id = next(iter(payload["questions"]))
            return {"answers": {question_id: {"type": "choice", "choice": "x"}}}

        selector = KevSelector(
            transport=invalid_post,
            metadata_transport=self.metadata,
            require_cuda=True,
        )
        with self.assertRaisesRegex(RuntimeError, "알 수 없는 후보"):
            selector.select_route("state", {"route_a": "A", "route_b": "B"})


if __name__ == "__main__":
    unittest.main()
