"""Ollaya typed-decision 타입과 반복 벤치마크를 Mock으로 검증한다."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from simulation.evaluation.ollaya_question_types_benchmark import CASES, run_question_types_benchmark
from simulation.route_selector.ollaya_laya_selector import OllayaLayaSelector


class OllayaTypedDecisionTest(unittest.TestCase):
    def test_selector_parses_score_and_noul_answers(self):
        def transport(_url, payload, _headers, _timeout):
            question_id, question = next(iter(payload["questions"].items()))
            if question["type"] == "score":
                answer = {"type": "score", "score": 3.8, "confidence": 0.9, "legend": {"0": "low", "4": "high"}, "probabilities": {"0": 0.01, "4": 0.91}}
            else:
                answer = {"type": "noul", "noul": 0.95}
            return {"model": "laya:multilingual", "answers": {question_id: answer}, "eval_duration": 10_000_000}

        selector = OllayaLayaSelector(transport=transport)
        score = selector.evaluate_score("state", ["a", "b", "c", "d", "e"], "rate", question_id="urgency")
        noul = selector.evaluate_noul("state", "is stopped", question_id="stopped")
        self.assertEqual(score["score"], 3.8)
        self.assertEqual(score["eval_duration_seconds"], 0.01)
        self.assertEqual(noul["noul"], 0.95)

    def test_benchmark_exports_question_type_cases(self):
        class FakeSelector:
            model = "laya:multilingual"
            def select_choice(self, *_args, **_kwargs):
                return self.result(choice="red", confidence=0.9, probabilities={"red": 0.9})
            def evaluate_score(self, *_args, **_kwargs):
                return self.result(score=3.8, confidence=0.8, probabilities={"4": 0.8}, legend={"4": "high"})
            def evaluate_noul(self, *_args, **_kwargs):
                return self.result(noul=0.95)
            @staticmethod
            def result(**values):
                return {"model": "laya:multilingual", "total_duration_seconds": 0.02, "load_duration_seconds": 0.0, "eval_duration_seconds": 0.01, "raw": {}, **values}

        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "run"
            values = iter(value for index in range(16) for value in (float(index), float(index) + 0.1))
            summary = run_question_types_benchmark(output, repeats=2, warmups=1, selector=FakeSelector(), clock=lambda: next(values), progress=False)
            self.assertEqual(len(CASES), 8)
            blocked_case = next(
                case for case in CASES if case["id"] == "ko_route_blocked_noul"
            )
            self.assertIn(6, blocked_case["state"]["planned_route"])
            self.assertIn(6, blocked_case["state"]["blocked_nodes"])
            self.assertTrue(blocked_case["expected_boolean"])
            english_blocked_case = next(
                case for case in CASES if case["id"] == "en_route_blocked_noul"
            )
            self.assertEqual(
                english_blocked_case["state"], blocked_case["state"] | {
                    "rule": "A route cannot be used when it contains a blocked node."
                },
            )
            self.assertEqual(
                english_blocked_case["instructions"],
                "Is the current route unavailable?",
            )
            self.assertTrue(english_blocked_case["expected_boolean"])
            self.assertEqual(summary["settings"]["expected_trial_count"], 16)
            self.assertEqual(summary["overall"]["correct_count"], 16)
            self.assertEqual(len(summary["groups"]), 6)
            self.assertEqual(len((output / "ollaya_question_type_trials.jsonl").read_text(encoding="utf-8").splitlines()), 16)
            self.assertTrue((output / "ollaya_question_type_summary.json").is_file())
            self.assertTrue((output / "ollaya_question_type_samples.csv").is_file())


if __name__ == "__main__":
    unittest.main()
