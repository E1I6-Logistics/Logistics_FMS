"""모델 다운로드 없이 Hugging Face Laya CUDA selector를 검증한다."""

from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from simulation.route_selector.laya_selector import LayaSelector
from simulation.route_selector.registry import get_selector


class _Device:
    def __init__(self, value: str):
        self.value = value
        self.type = value.split(":", 1)[0]

    def __str__(self) -> str:
        return self.value


class _FakeAgent:
    def __init__(self, device: str = "cuda:0"):
        self.device = _Device(device)
        self.dtype = "torch.float16"
        self.cpu_fallback_count = 0
        self.calls = []
        self.closed = False

    def predict(self, state, questions, *, max_len):
        self.calls.append((state, questions, max_len))
        question_id, question = next(iter(questions.items()))
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
            "model": "laya-rl-agent",
            "answers": {question_id: answer},
            "usage": {"input_tokens": 32, "output_tokens": 1},
        }

    def __exit__(self, *_args):
        self.closed = True


class LayaSelectorTest(unittest.TestCase):
    def test_lazy_loads_one_cuda_model_and_reuses_it(self):
        agent = _FakeAgent()
        loads = []

        def loader(**kwargs):
            loads.append(kwargs)
            return agent

        selector = LayaSelector(
            model="convaiinnovations/laya-multilingual",
            device="cuda:0",
            max_length=1024,
            require_cuda=True,
            hf_token="token",
            loader=loader,
        )
        candidates = {"route_a": "long", "route_b": "short"}
        first = selector.select_route("state", candidates)
        second = selector.select_route("state", candidates)

        self.assertEqual(len(loads), 1)
        self.assertEqual(loads[0]["device"], "cuda:0")
        self.assertEqual(loads[0]["token"], "token")
        self.assertEqual(len(agent.calls), 2)
        self.assertTrue(all(call[2] == 1024 for call in agent.calls))
        self.assertEqual(first["choice"], "route_b")
        self.assertEqual(second["runtime"]["device"], "cuda:0")
        self.assertEqual(second["runtime"]["precision"], "float16")
        self.assertEqual(second["load_duration_seconds"], 0.0)

    def test_supports_score_and_noul_with_same_interface(self):
        selector = LayaSelector(
            require_cuda=True, loader=lambda **_kwargs: _FakeAgent()
        )
        score = selector.evaluate_score(
            "state", ["a", "b", "c", "d", "e"], "rate"
        )
        noul = selector.evaluate_noul("state", "is stopped")

        self.assertEqual(score["score"], 3.8)
        self.assertEqual(noul["noul"], 0.95)

    def test_rejects_silent_cpu_fallback_at_load(self):
        selector = LayaSelector(
            require_cuda=True, loader=lambda **_kwargs: _FakeAgent("cpu")
        )
        with self.assertRaisesRegex(RuntimeError, "CUDA에 올라가지 않았습니다"):
            selector.select_route("state", {"route_a": "A", "route_b": "B"})

    def test_release_frees_the_loaded_agent(self):
        agent = _FakeAgent()
        selector = LayaSelector(loader=lambda **_kwargs: agent)
        selector.select_route("state", {"route_a": "A", "route_b": "B"})
        selector.release()

        self.assertTrue(agent.closed)
        self.assertIsNone(selector._agent)

    def test_registry_defaults_to_laya_selector(self):
        clean_environment = {
            key: value
            for key, value in os.environ.items()
            if key != "ROUTE_SELECTOR"
        }
        with patch.dict(os.environ, clean_environment, clear=True):
            selector = get_selector()
        self.assertIsInstance(selector, LayaSelector)


if __name__ == "__main__":
    unittest.main()
